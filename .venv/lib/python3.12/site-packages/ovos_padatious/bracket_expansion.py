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

"""Deprecated local sentence-tree parser.

Parenthesis expansion is provided by ``ovos_spec_tools.expand`` (operating on
the raw template string). The token-based classes below remain only as
deprecation shims to preserve the public API.
"""

import warnings

from ovos_utils.log import deprecated

from ovos_padatious.version import VERSION_MAJOR

_REMOVAL = f"{VERSION_MAJOR + 1}.0.0"


def _warn(symbol: str) -> None:
    warnings.warn(
        f"ovos_padatious.bracket_expansion.{symbol} is deprecated; "
        f"use ovos_spec_tools.expand instead. Removal: {_REMOVAL}",
        DeprecationWarning,
        stacklevel=3,
    )


class Fragment(object):
    """(Abstract) empty sentence fragment. Deprecated."""

    @deprecated("use ovos_spec_tools.expand", _REMOVAL)
    def __init__(self, tree):
        _warn("Fragment")
        self._tree = tree

    def tree(self):
        return self._tree

    def expand(self):
        return [[]]

    def __str__(self):
        return self._tree.__str__()

    def __repr__(self):
        return self._tree.__repr__()


class Word(Fragment):
    """Single word in the sentence tree. Deprecated."""

    def expand(self):
        return [[self._tree]]


class Sentence(Fragment):
    """A Sentence made of several concatenations/words. Deprecated."""

    def expand(self):
        old_expanded = [[]]
        for sub in self._tree:
            sub_expanded = sub.expand()
            new_expanded = []
            while len(old_expanded) > 0:
                sentence = old_expanded.pop()
                for new in sub_expanded:
                    new_expanded.append(sentence + new)
            old_expanded = new_expanded
        return old_expanded


class Options(Fragment):
    """A Combination of possible sub-sentences. Deprecated."""

    def expand(self):
        options = []
        for option in self._tree:
            options.extend(option.expand())
        return options


class SentenceTreeParser(object):
    """Token-based sentence tree parser. Deprecated.

    Prefer ``ovos_spec_tools.expand`` on the raw template string.
    """

    @deprecated("use ovos_spec_tools.expand", _REMOVAL)
    def __init__(self, tokens):
        _warn("SentenceTreeParser")
        self.tokens = tokens

    def _parse(self):
        self._current_position = 0
        return self._parse_expr()

    def _parse_expr(self):
        sentence_list = []
        cur_sentence = []
        sentence_list.append(Sentence(cur_sentence))
        while self._current_position < len(self.tokens):
            cur = self.tokens[self._current_position]
            self._current_position += 1
            if cur == '(':
                subexpr = self._parse_expr()
                normal_brackets = False
                if len(subexpr.tree()) == 1:
                    normal_brackets = True
                    cur_sentence.append(Word('('))
                cur_sentence.append(subexpr)
                if normal_brackets:
                    cur_sentence.append(Word(')'))
            elif cur == '|':
                cur_sentence = []
                sentence_list.append(Sentence(cur_sentence))
            elif cur == ')':
                break
            else:
                cur_sentence.append(Word(cur))
        return Options(sentence_list)

    def _expand_tree(self, tree):
        return tree.expand()

    def expand_parentheses(self):
        tree = self._parse()
        return self._expand_tree(tree)
