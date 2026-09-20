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

import json
from os.path import isfile, join
from typing import Any, List, Set, Tuple, Type

from ovos_padatious.simple_intent import SimpleIntent
from ovos_padatious.trainable import Trainable

#: Upper bound on sentences fed to the entity's neural net, positives and
#: negatives each. Net training cost grows with vocabulary width times sample
#: count times epochs, and past a few hundred diverse samples the net stops
#: converging, so every training restart burns its full epoch budget: an
#: unbounded pair of ~2200-value entities trains for over ten minutes where
#: the capped net takes about a second. The net only needs enough examples to
#: generalise over *unseen* values — every known value is matched exactly
#: through ``Entity.samples`` instead, so capping the net's diet loses
#: nothing for listed values.
ENTITY_NET_TRAINING_CAP = 128


class _CappedTrainData:
    """View of a ``TrainData`` that bounds one entity's positive and negative
    sentence streams to a deterministic, evenly-strided subset."""

    def __init__(self, data: Any, name: str,
                 keep_mine: Set[Tuple[str, ...]],
                 keep_other: Set[Tuple[str, ...]]) -> None:
        self._data = data
        self._name = name
        self._keep_mine = keep_mine
        self._keep_other = keep_other

    def my_sents(self, name: str):
        seen = set()
        for sent in self._data.my_sents(name):
            key = tuple(sent)
            if key in self._keep_mine and key not in seen:
                seen.add(key)
                yield sent

    def other_sents(self, name: str):
        seen = set()
        for sent in self._data.other_sents(name):
            key = tuple(sent)
            if key in self._keep_other and key not in seen:
                seen.add(key)
                yield sent


def _strided_subset(sents: List[Tuple[str, ...]], cap: int) -> Set[Tuple[str, ...]]:
    """Deterministic evenly-strided pick of ``cap`` items from sorted input."""
    if len(sents) <= cap:
        return set(sents)
    step = (len(sents) - 1) / (cap - 1)
    return {sents[round(i * step)] for i in range(cap)}


class Entity(SimpleIntent, Trainable):
    def __init__(self, name: str, *args: Any, **kwargs: Any) -> None:
        """
        Initializes an Entity instance.

        Args:
            name (str): The name of the entity.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        SimpleIntent.__init__(self, name)
        Trainable.__init__(self, name, *args, **kwargs)
        #: Every known value as a token tuple. Exact lookups bypass the net:
        #: a listed value always scores 1.0, deterministically, regardless of
        #: how the (retraining-nondeterministic) net would score it.
        self.samples: Set[Tuple[str, ...]] = set()

    def match(self, sent: List[str]) -> float:
        if tuple(sent) in self.samples:
            return 1.0
        return SimpleIntent.match(self, sent)

    def train(self, train_data: Any) -> None:
        mine = sorted({tuple(s) for s in train_data.my_sents(self.name)})
        self.samples = set(mine)
        other = sorted({tuple(s) for s in train_data.other_sents(self.name)})
        if len(mine) > ENTITY_NET_TRAINING_CAP or len(other) > ENTITY_NET_TRAINING_CAP:
            train_data = _CappedTrainData(
                train_data, self.name,
                _strided_subset(mine, ENTITY_NET_TRAINING_CAP),
                _strided_subset(other, ENTITY_NET_TRAINING_CAP))
        SimpleIntent.train(self, train_data)

    @staticmethod
    def verify_name(token: str) -> None:
        """
        Verifies that the token is not surrounded by braces.

        Args:
            token (str): The token to verify.

        Raises:
            ValueError: If the token is surrounded by braces.
        """
        if token.startswith('{') or token.endswith('}'):
            raise ValueError('Token must not be surrounded in braces (e.g., {word} should be word)')

    @staticmethod
    def wrap_name(name: str) -> str:
        """
        Wraps the skill name and entity into a specific format.

        Args:
            name (str): The skill name or entity name.

        Returns:
            str: Wrapped name in the format SkillName:{entity}.
        """
        if ':' in name:
            parts = name.split(':')
            intent_name, ent_name = parts[0], parts[1:]
            return f"{intent_name}:{{{':'.join(ent_name)}}}"
        else:
            return f"{{{name}}}"

    def save(self, folder: str) -> None:
        """
        Saves the entity to the specified folder.

        Args:
            folder (str): The folder path where the entity should be saved.
        """
        prefix = join(folder, self.name)
        SimpleIntent.save(self, prefix)
        with open(prefix + '.samples', 'w', encoding='utf-8') as f:
            json.dump(sorted(list(s) for s in self.samples), f, ensure_ascii=False)
        self.save_hash(prefix)

    @classmethod
    def from_file(cls: Type['Entity'], name: str, folder: str) -> 'Entity':
        """
        Creates an Entity instance from a file.

        Args:
            cls (Type[Entity]): The class itself.
            name (str): The name of the entity.
            folder (str): The folder path where the entity file is located.

        Returns:
            Entity: The loaded Entity instance.
        """
        self = super(Entity, cls).from_file(name, join(folder, name))
        samples_file = join(folder, name) + '.samples'
        if isfile(samples_file):
            with open(samples_file, encoding='utf-8') as f:
                self.samples = {tuple(s) for s in json.load(f)}
        self.load_hash(join(folder, name))
        return self
