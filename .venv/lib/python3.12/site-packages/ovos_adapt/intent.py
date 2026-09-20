# Copyright 2018 Mycroft AI Inc.
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

__author__ = 'seanfitz'

import itertools

from ovos_spec_tools.intent import Intent as _SpecIntent
from ovos_spec_tools.intent import IntentBuilder as _SpecIntentBuilder
from ovos_spec_tools.intent import open_intent_envelope as _spec_open_intent_envelope

CLIENT_ENTITY_NAME = 'Client'


class Intent(_SpecIntent):
    """An adapt intent parser carrying its own matching logic.

    This is the adapt engine's matching primitive: every parser registered
    with :class:`~ovos_adapt.engine.IntentDeterminationEngine` must expose
    :meth:`validate` / :meth:`validate_with_tags`.

    The **declarative** half — the ``name`` / ``requires`` / ``at_least_one`` /
    ``optional`` / ``excludes`` role lists and :meth:`to_keyword_payload`
    emission — is the canonical OVOS-INTENT-4 :class:`ovos_spec_tools.intent.Intent`
    DTO, which this class subclasses rather than duplicates. Only the
    adapt-engine **matching** logic (:meth:`validate` /
    :meth:`validate_with_tags` and the private tag-search helpers) lives here.

    Subclasses of this remain ``isinstance`` of the spec-tools DTO, so anything
    consuming the INTENT-4 definition surface (e.g. registration producers)
    works unchanged on an adapt parser.
    """

    def validate(self, tags, confidence):
        """Using this method removes tags from the result of validate_with_tags

        Returns:
            intent(intent): Results from validate_with_tags
        """
        intent, tags = self.validate_with_tags(tags, confidence)
        return intent

    def validate_with_tags(self, tags, confidence):
        """Validate whether tags has required entites for this intent to fire

        Args:
            tags(list): Tags and Entities used for validation
            confidence(float): The weight associate to the parse result,
                as indicated by the parser. This is influenced by a parser
                that uses edit distance or context.

        Returns:
            intent, tags: Returns intent and tags used by the intent on
                failure to meat required entities then returns intent with
                confidence
                of 0.0 and an empty list for tags.
        """
        result = {'intent_type': self.name}
        intent_confidence = 0.0
        local_tags = tags[:]
        used_tags = []

        # Check excludes first
        for exclude_type in self.excludes:
            exclude_tag, _canonical_form, _tag_confidence = \
                self._find_first_tag(local_tags, exclude_type)
            if exclude_tag:
                result['confidence'] = 0.0
                return result, []

        for require_type, attribute_name in self.requires:
            required_tag, canonical_form, tag_confidence = \
                self._find_first_tag(local_tags, require_type)
            if not required_tag:
                result['confidence'] = 0.0
                return result, []

            result[attribute_name] = canonical_form
            if required_tag in local_tags:
                local_tags.remove(required_tag)
            used_tags.append(required_tag)
            intent_confidence += tag_confidence

        if len(self.at_least_one) > 0:
            best_resolution = self._resolve_one_of(local_tags, self.at_least_one)
            if not best_resolution:
                result['confidence'] = 0.0
                return result, []
            else:
                for key in best_resolution:
                    # TODO: at least one should support aliases
                    result[key] = best_resolution[key][0].get('key')
                    intent_confidence += 1.0 * best_resolution[key][0]['entities'][0].get('confidence', 1.0)
                used_tags.append(best_resolution[key][0])
                if best_resolution in local_tags:
                    local_tags.remove(best_resolution[key][0])

        for optional_type, attribute_name in self.optional:
            optional_tag, canonical_form, tag_confidence = \
                self._find_first_tag(local_tags, optional_type)
            if not optional_tag or attribute_name in result:
                continue
            result[attribute_name] = canonical_form
            if optional_tag in local_tags:
                local_tags.remove(optional_tag)
            used_tags.append(optional_tag)
            intent_confidence += tag_confidence

        total_confidence = (intent_confidence / len(tags) * confidence) \
            if tags else 0.0

        target_client, canonical_form, confidence = \
            self._find_first_tag(local_tags, CLIENT_ENTITY_NAME)

        result['target'] = target_client.get('key') if target_client else None
        result['confidence'] = total_confidence

        return result, used_tags

    @classmethod
    def _resolve_one_of(cls, tags, at_least_one):
        """Search through all combinations of at_least_one rules to find a
        combination that is covered by tags

        Args:
            tags(list): List of tags with Entities to search for Entities
            at_least_one(list): List of Entities to find in tags

        Returns:
            object:
            returns None if no match is found but returns any match as an object
        """
        for possible_resolution in itertools.product(*at_least_one):
            resolution = {}
            pr = possible_resolution[:]
            for entity_type in pr:
                last_end_index = -1
                if entity_type in resolution:
                    last_end_index = resolution[entity_type][-1].get('end_token')
                tag, value, c = cls._find_first_tag(tags, entity_type,
                                                    after_index=last_end_index)
                if not tag:
                    break
                else:
                    if entity_type not in resolution:
                        resolution[entity_type] = []
                    resolution[entity_type].append(tag)
            # Check if this is a valid resolution (all one_of rules matched)
            if len(resolution) == len(possible_resolution):
                return resolution

        return None

    @staticmethod
    def _find_first_tag(tags, entity_type, after_index=-1):
        """Searches tags for entity type after given index

        Args:
            tags(list): a list of tags with entity types to be compared to
             entity_type
            entity_type(str): This is he entity type to be looking for in tags
            after_index(int): the start token must be greater than this.

        Returns:
            ( tag, v, confidence ):
                tag(str): is the tag that matched
                v(str): ? the word that matched?
                confidence(float): is a measure of accuracy.  1 is full confidence
                    and 0 is none.
        """
        for tag in tags:
            for entity in tag.get('entities'):
                for v, t in entity.get('data'):
                    if t.lower() == entity_type.lower() and \
                            (tag.get('start_token', 0) > after_index or
                             tag.get('from_context', False)):
                        return tag, v, entity.get('confidence')

        return None, None, None


class IntentBuilder(_SpecIntentBuilder):
    """IntentBuilder, used to construct adapt intent parsers.

    Inherits the fluent ``require`` / ``optionally`` / ``one_of`` / ``exclude``
    role accumulation from the canonical OVOS-INTENT-4
    :class:`ovos_spec_tools.intent.IntentBuilder`. Only :meth:`build` is
    overridden, so the produced object is adapt's matching :class:`Intent`
    (which is itself a spec-tools ``Intent``) rather than the bare DTO.

    Notes:
        This is designed to allow construction of intents in one line.

    Example:
        IntentBuilder("Intent")\
            .require("A")\
            .one_of("C","D")\
            .optional("G").build()
    """

    def build(self):
        """Constructs an adapt :class:`Intent` from the builder's specifications.

        :return: an Intent instance with adapt matching logic.
        """
        return Intent(self.name, self.requires,
                      self.at_least_one, self.optional,
                      self.excludes)


def open_intent_envelope(message):
    """Convert dictionary received over messagebus to adapt :class:`Intent`.

    Parses the envelope with the canonical spec-tools helper (which accepts
    both the legacy and OVOS-INTENT-4 §5.2 wire keys) and re-wraps the result
    as adapt's matching :class:`Intent`.
    """
    spec_intent = _spec_open_intent_envelope(message)
    return Intent(spec_intent.name, spec_intent.requires,
                  spec_intent.at_least_one, spec_intent.optional,
                  spec_intent.excludes)


def is_entity(tag, entity_name):
    for entity in tag.get('entities'):
        for v, t in entity.get('data'):
            if t.lower() == entity_name.lower():
                return True
    return False


def find_first_tag(tags, entity_type, after_index=-1):
    """Searches tags for entity type after given index

    Args:
        tags(list): a list of tags with entity types to be compared to
         entity_type
        entity_type(str): This is he entity type to be looking for in tags
        after_index(int): the start token must be greater than this.

    Returns:
        ( tag, v, confidence ):
            tag(str): is the tag that matched
            v(str): ? the word that matched?
            confidence(float): is a measure of accuracy.  1 is full confidence
                and 0 is none.
    """
    return Intent._find_first_tag(tags, entity_type, after_index)


def find_next_tag(tags, end_index=0):
    for tag in tags:
        if tag.get('start_token') > end_index:
            return tag
    return None


def choose_1_from_each(lists):
    """
    The original implementation here was functionally equivalent to
    :func:`~itertools.product`, except that the former returns a generator
    of lists, and itertools returns a generator of tuples. This is going to do
    a light transform for now, until callers can be verified to work with
    tuples.

    Args:
        A list of lists or tuples, expected as input to
        :func:`~itertools.product`

    Returns:
        a generator of lists, see docs on :func:`~itertools.product`
    """
    for result in itertools.product(*lists):
        yield list(result)


def resolve_one_of(tags, at_least_one):
    """Search through all combinations of at_least_one rules to find a
    combination that is covered by tags

    Args:
        tags(list): List of tags with Entities to search for Entities
        at_least_one(list): List of Entities to find in tags

    Returns:
        object:
        returns None if no match is found but returns any match as an object
    """
    return Intent._resolve_one_of(tags, at_least_one)
