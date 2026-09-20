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

import math
from typing import List, Optional, Any

from ovos_padatious.entity_edge import EntityEdge
from ovos_padatious.match_data import MatchData

#: Lowest contribution a registered entity value set may make to a candidate.
#:
#: Per OVOS-INTENT-1 5.4 an ``.entity`` file (or ``add_entity`` call) is a set
#: of *training hints*: example values that bias scoring towards the expected
#: shape of a slot. It is NOT a closed vocabulary. The spec is normative here -
#: an engine MAY use the set to *score* a slot, but MUST NOT treat it as an
#: exhaustive allow-list, so a candidate whose slot fills with a value outside
#: the set MUST remain matchable.
#:
#: So the raw ``Entity.match`` score is mapped through :func:`hint_confidence`,
#: which lifts it onto a floor without ever letting it collapse a candidate.
ENTITY_HINT_FLOOR = 0.8

#: Raw score at and above which :func:`hint_confidence` is the identity.
#:
#: A *listed* value short-circuits through ``Entity.samples`` to a raw score
#: of exactly 1.0, which the identity passes through unchanged: the slot
#: scores bit-identically to a hint-less slot (``ent_conf == 1.0``), so
#: attaching an entity never penalises the values it knows. The net only
#: scores *unlisted* values, and those must not be lifted into this band by
#: rescaling - the obvious ``1 - bias * (1 - raw)`` promotes weak
#: recognitions across pipeline confidence thresholds. Keeping the map an
#: identity from here up, and a ramp below, makes that impossible.
ENTITY_HINT_IDENTITY = 0.9

#: Raw ``Entity.match`` score above which the value set is considered to have
#: actually recognised a span. Only then is it used to discard rival spans.
ENTITY_HINT_RECOGNISED = 0.5


def hint_confidence(raw: float) -> float:
    """Map a raw ``Entity.match`` score to a slot-scoring contribution.

    The map is **strictly increasing** on ``[0, 1]``, and that is the whole
    design. Two properties have to hold at once:

    * a value the set does not know must not collapse its candidate, so the
      map has a floor at :data:`ENTITY_HINT_FLOOR` and never returns less;
    * the set must still be able to *rank* rival spans that it recognises
      only weakly. A flat floor cannot: with two spans both mapping to 0.8,
      the tie falls to ``pos_conf``, which prefers the shorter span, and
      "play song 2" extracts "2" instead of "song 2". Strict monotonicity is
      what keeps a partial recognition worth more than none at all.

    Below :data:`ENTITY_HINT_IDENTITY` the score is ramped from the floor by a
    square root, so the interesting, weakly-recognised end of the range gets
    most of the resolution. At and above it the map is the identity: a listed
    value arrives here as an exact 1.0 (``Entity.samples``) and passes through
    unchanged, and an unlisted value the net happens to score highly is not
    rescaled any further.
    """
    raw = min(1.0, max(0.0, raw))
    if raw >= ENTITY_HINT_IDENTITY:
        return raw
    span = ENTITY_HINT_IDENTITY - ENTITY_HINT_FLOOR
    return ENTITY_HINT_FLOOR + span * math.sqrt(raw / ENTITY_HINT_IDENTITY)


class PosIntent:
    """
    A class for handling positional intents used to extract entities from sentences.

    Args:
        token (str): The token to attach to (something like {word}).
        intent_name (str): Optional name of the intent. Defaults to an empty string.
    """

    def __init__(self, token: str, intent_name: str = '') -> None:
        self.token = token
        self.edges: List[EntityEdge] = [
            EntityEdge(-1, token, intent_name),
            EntityEdge(+1, token, intent_name)
        ]

    def match(self, orig_data: Any, entity: Optional[Any] = None,
              template_tokens: Optional[Any] = None) -> List[MatchData]:
        """
        Matches the original data against the token and extracts entities.

        Args:
            orig_data (Any): Original data containing the sentence to match.
            entity (Optional[Any]): An entity to match against. Defaults to None.
            template_tokens (Optional[Any]): Container supporting ``in`` that
                holds the literal tokens of this intent's own templates. Used
                only to discard a rival span that swallows template literals
                around a span the value set recognised. Defaults to None.

        Returns:
            List[MatchData]: A list of possible matches with their corresponding data.
        """
        l_matches = [(self.edges[0].match(orig_data.sent, pos), pos)
                     for pos in range(len(orig_data.sent))]
        r_matches = [(self.edges[1].match(orig_data.sent, pos), pos)
                     for pos in range(len(orig_data.sent))]

        def is_valid(l_pos: int, r_pos: int) -> bool:
            """Check if the positions are valid for matching."""
            if r_pos < l_pos:
                return False
            return all(not orig_data.sent[p].startswith('{') for p in range(l_pos, r_pos + 1))

        scored: List[tuple] = []
        for l_conf, l_pos in l_matches:
            if l_conf < 0.2:
                continue
            for r_conf, r_pos in r_matches:
                if r_conf < 0.2 or not is_valid(l_pos, r_pos):
                    continue

                extracted = orig_data.sent[l_pos:r_pos + 1]

                pos_conf = (l_conf - 0.5 + r_conf - 0.5) / 2 + 0.5
                # entity value sets are training hints, not vocabularies:
                # a LISTED value short-circuits to exactly 1.0 through
                # Entity.samples, scoring as if no hint were attached, and an
                # unlisted value is floor-ramped by the net - never collapsed
                # (and so never discarded)
                raw = 1.0
                if entity:
                    raw = min(1.0, max(0.0, entity.match(extracted)))
                ent_conf = hint_confidence(raw) if entity else 1.0

                new_sent = orig_data.sent[:l_pos] + [self.token] + orig_data.sent[r_pos + 1:]
                new_matches = orig_data.matches.copy()
                new_matches[self.token] = extracted

                extra_conf = math.sqrt(pos_conf * ent_conf) - 0.5
                data = MatchData(orig_data.name, new_sent, new_matches,
                                 orig_data.conf + extra_conf)
                scored.append((raw, l_pos, r_pos, data))

        # With no entity every span scores raw 1.0, so there is no "recognised"
        # span to discriminate around and the value set steers nothing. Bail
        # out before the filter, or an entity-less slot would silently lose
        # spans to an arbitrary tie-broken "best".
        if not scored or entity is None or template_tokens is None:
            return [data for _, _, _, data in scored]

        # A value set still steers *which* words fill the slot, but only in the
        # one case where the alternative is unambiguously wrong: a rival span
        # that strictly contains a span the set recognised, and whose extra
        # words are literals of this intent's own templates. "make a timer for
        # 3 minute" against a numeric value set drops "timer for 3" in favour
        # of "3", because "timer" and "for" are template literals.
        #
        # Anything else survives. In particular a multi-word out-of-list value
        # whose tail happens to be listed keeps its full span - "weather in new
        # london" yields "new london", not "london", because "new" is not a
        # template literal. Discarding on raw score alone truncated those.
        best_raw, best_l, best_r, _ = max(scored, key=lambda s: s[0])
        if best_raw < ENTITY_HINT_RECOGNISED:
            return [data for _, _, _, data in scored]

        def swallows_only_literals(l_pos: int, r_pos: int) -> bool:
            if (l_pos, r_pos) == (best_l, best_r):
                return False
            if l_pos > best_l or r_pos < best_r:
                return False  # not a strict superset of the recognised span
            extra = (list(range(l_pos, best_l)) +
                     list(range(best_r + 1, r_pos + 1)))
            return all(orig_data.sent[p] in template_tokens for p in extra)

        return [data for _, l_pos, r_pos, data in scored
                if not swallows_only_literals(l_pos, r_pos)]

    def save(self, prefix: str) -> None:
        """
        Saves the positional intent's data.

        Args:
            prefix (str): The prefix to use for the saved data.
        """
        prefix += '.' + self.token
        for edge in self.edges:
            edge.save(prefix)

    @classmethod
    def from_file(cls, prefix: str, token: str) -> 'PosIntent':
        """
        Creates a PosIntent instance from saved data.

        Args:
            prefix (str): The prefix used for saved data.
            token (str): The token associated with the intent.

        Returns:
            PosIntent: A new instance of PosIntent.
        """
        prefix += '.' + token
        instance = cls(token)
        for edge in instance.edges:
            edge.load(prefix)
        return instance

    def train(self, train_data: Any) -> None:
        """
        Trains the positional intent on the provided training data.

        Args:
            train_data (Any): The data to train on.
        """
        for edge in self.edges:
            edge.train(train_data)
