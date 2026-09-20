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

from ovos_padatious.entity import Entity
from ovos_padatious.training_manager import TrainingManager


class EntityManager(TrainingManager):
    """
    Manages entities and their training processes.

    Args:
        cache (str): Path to the cache directory.
    """

    def __init__(self, cache: str) -> None:
        super(EntityManager, self).__init__(Entity, cache)
        self.entity_dict: dict[str, Entity] = {}

    def calc_ent_dict(self) -> None:
        """
        Calculates the entity dictionary from the current objects.
        """
        for i in self.objects:
            self.entity_dict[i.name] = i

    def find(self, intent_name: str, token: str) -> Entity | None:
        """
        Finds an entity based on the intent name and token.

        Args:
            intent_name (str): The name of the intent.
            token (str): The token to search for.

        Returns:
            Entity | None: The corresponding entity or None if not found.
        """
        local_name, global_name = '', token
        if ':' in intent_name:
            local_name = intent_name.split(':')[0] + ':' + token
        return self.entity_dict.get(local_name, self.entity_dict.get(global_name))

    def remove(self, name: str) -> None:
        """
        Removes an entity from the manager.

        Args:
            name (str): The name of the entity to remove. Accepted either
                bare (``<skill_id>:<entity>`` / ``<entity>``) or already
                wrapped (``<skill_id>:{<entity>}`` / ``{<entity>}``).
        """
        # entities are stored under Entity.wrap_name(), i.e.
        # ``<skill_id>:{<entity>}`` - the brace goes around the entity token
        # only, NOT around the whole namespaced name. Wrapping blindly here
        # produced ``{<skill_id>:<entity>}``, which matched nothing, so no
        # entity was ever removable and TrainingManager.add's replace-on-
        # re-register stacked duplicate objects instead of collapsing them.
        if '{' not in name:
            name = Entity.wrap_name(name)
        if name in self.entity_dict:
            del self.entity_dict[name]
        super(EntityManager, self).remove(name)
