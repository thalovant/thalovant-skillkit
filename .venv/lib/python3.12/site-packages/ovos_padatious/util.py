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

from ovos_utils import flatten_list
from ovos_utils.log import LOG, log_deprecation
from ovos_spec_tools import expand as expand_template
from ovos_spec_tools.expansion import MalformedTemplate

from xxhash import xxh32
from ovos_padatious.bracket_expansion import SentenceTreeParser
from ovos_padatious.version import VERSION_MAJOR

_HASH_WILDCARD_REMOVAL = f"{VERSION_MAJOR + 1}.0.0"


def lines_hash(lines):
    """
    Creates a unique binary id for the given lines
    Args:
        lines (list<str>): List of strings that should be collectively hashed
    Returns:
        bytearray: Binary hash
    """
    x = xxh32()
    for i in sorted(lines):
        x.update(i.encode())
    return x.digest()


def tokenize(sentence):
    """
    Converts a single sentence into a list of individual significant units
    Args:
        sentence (str): Input string ie. 'This is a sentence.'
    Returns:
        list<str>: List of tokens ie. ['this', 'is', 'a', 'sentence']
    """
    tokens = []

    class Vars:
        start_pos = -1
        last_type = 'o'
        in_brace = False

    def update(c, i):
        # '_' is grouped with the alpha/word class rather than treated as a
        # break character. This matters most for template slot placeholders
        # such as '{pokemon_a}': the '{' and '}' are also in this class, so
        # the whole placeholder tokenizes as a single token '{pokemon_a}'
        # instead of splitting into ['{pokemon', '_', 'a}']. Downstream code
        # (Intent.train, EntityManager.find, Entity.wrap_name, ...) all key
        # off a token that starts with '{' and ends with '}' to recognize a
        # slot - a split placeholder silently produces a bogus PosIntent
        # token and an entity name that never resolves.
        #
        # tokenize() is shared by template lines (training side) AND by
        # plain user utterances (runtime match side), so this also changes
        # how a literal underscore in an utterance tokenizes: 'foo_bar' now
        # becomes ['foo_bar'] instead of ['foo', '_', 'bar']. That is an
        # accepted, deliberate side effect: word_with_underscore is already
        # one identifier/word to a human, splitting on '_' was never useful
        # for matching ordinary text, and keeping it whole makes template
        # and utterance tokenization behave consistently for the same input.
        #
        # Digits get the same brace-scoped treatment, but ONLY inside a
        # '{...}' span: '{slot_1}' must tokenize as one token exactly like
        # '{slot_a}' does, otherwise the same bug resurfaces for any slot
        # name that happens to contain a digit. Outside of braces, digits
        # keep splitting from letters exactly as before ('one1' -> ['one',
        # '1']) - IdManager.adj_token() (id_manager.py) relies on isolated
        # pure-digit tokens to canonicalize numbers to '#' placeholders for
        # the neural net, and tests/test_util.py pins 'one1 two2' ->
        # ['one', '1', 'two', '2'] as existing, load-bearing behavior that
        # must not change.
        if c == '{':
            Vars.in_brace = True
        elif c == '}':
            Vars.in_brace = False

        if c.isalpha() or c in '-_{}' or (Vars.in_brace and (c.isdigit() or c == '#')):
            t = 'a'
        elif c.isdigit() or c == '#':
            t = 'n'
        elif c.isspace():
            t = 's'
        else:
            t = 'o'

        if t != Vars.last_type or t == 'o':
            if Vars.start_pos >= 0:
                token = sentence[Vars.start_pos:i].lower()
                if token not in '.!?':
                    tokens.append(token)
            Vars.start_pos = -1 if t == 's' else i
        Vars.last_type = t

    for i, char in enumerate(sentence):
        update(char, i)
    update(' ', len(sentence))
    return tokens


def expand_parentheses(sent):
    """
    ['1', '(', '2', '|', '3, ')'] -> [['1', '2'], ['1', '3']]
    For example:

    Will it (rain|pour) (today|tomorrow|)?

    ---->

    Will it rain today?
    Will it rain tomorrow?
    Will it rain?
    Will it pour today?
    Will it pour tomorrow?
    Will it pour?

    Args:
        sent (list<str>): List of tokens in sentence
    Returns:
        list<list<str>>: Multiple possible sentences from original
    """
    return SentenceTreeParser(sent).expand_parentheses()


def expand_or_skip(line, context=""):
    """Expand *line* via ``expand_template``, skipping it on failure.

    ``expand_template`` is deliberately strict per the intent template spec
    (e.g. it rejects single-branch groups like ``"cansad(e)"`` as
    :class:`MalformedTemplate`). That strictness is spec-side and must not be
    relaxed here. A single malformed line must not abort expansion of the
    remaining training lines, so on :class:`MalformedTemplate` we log a
    warning and contribute no samples for that line.

    Shared by every ``expand_template`` call site in this plugin (the
    file-based training path here in ``util.py`` and the messagebus
    registration path in ``opm.py``) so the tolerance behavior is defined
    exactly once.

    Args:
        line: Already-normalised training/sample line to expand.
        context: Optional human-readable identifier (e.g. ``"intent 'foo'"``)
            used in the warning log to name the offending registration.

    Returns:
        List of expanded variants, or ``[]`` if expansion failed.
    """
    try:
        return list(expand_template(line))
    except MalformedTemplate as e:
        LOG.warning(
            "malformed template%s: %r (%s) - skipping line",
            f" in {context}" if context else "", line, e,
        )
        return []


def expand_lines(lines):
    lines = [expand_or_skip(i) for i in remove_comments(lines) if i.strip()]
    return flatten_list(lines)


def remove_comments(lines):
    # NOTE: padatious considers comments as // but all of mycroft/OVOS uses #
    return [i for i in lines if not i.startswith('//')]


def warn_hash_wildcard(name, lines):
    """Deprecation warning for the inline '#' digit wildcard.

    ``#`` in a template line is a padatious-only extension: ``padaos``
    compiles it to a digit-class regex (``ovos_padatious.padaos``) and
    ``id_manager``/this module canonicalize literal digits to ``#`` for the
    neural net. No other OVOS intent engine understands it, it collides with
    the ``#``-as-comment-marker convention used elsewhere in the ecosystem,
    and it assumes the entity is spoken/ASR'd as a literal digit string. The
    portable replacement is a ``{slot}`` placeholder with skill-side number
    parsing.

    Behavior is unchanged this cycle - ``#`` still matches digits exactly as
    before. Warns at most once per call (ie. once per intent/entity
    registration).

    Args:
        name: Intent/entity name, used to identify the offender in the log.
        lines: Raw, not-yet-expanded template lines as registered.
    """
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('//') or stripped.startswith('#'):
            continue
        i = 0
        while i < len(stripped):
            c = stripped[i]
            if c == '\\':
                i += 2
                continue
            if c == '#':
                log_deprecation(
                    f"the inline '#' digit wildcard in {name!r} "
                    f"(line: {line!r}) is deprecated, use a `{{slot}}` "
                    "placeholder with skill-side number parsing instead",
                    _HASH_WILDCARD_REMOVAL,
                )
                return
            i += 1


def resolve_conflicts(inputs, outputs):
    """
    Checks for duplicate inputs and if there are any,
    remove one and set the output to the max of the two outputs
    Args:
        inputs (list<list<float>>): Array of input vectors
        outputs (list<list<float>>): Array of output vectors
    Returns:
        tuple<inputs, outputs>: The modified inputs and outputs
    """
    data = {}
    for inp, out in zip(inputs, outputs):
        tup = tuple(inp)
        if tup in data:
            data[tup].append(out)
        else:
            data[tup] = [out]

    inputs, outputs = [], []
    for inp, outs in data.items():
        inputs.append(list(inp))
        combined = [0] * len(outs[0])
        for i in range(len(combined)):
            combined[i] = max(j[i] for j in outs)
        outputs.append(combined)
    return inputs, outputs


class StrEnum(object):
    """Enum with strings as keys. Implements items method"""
    @classmethod
    def values(cls):
        return [getattr(cls, i) for i in dir(cls)
                if not i.startswith("__") and i != 'values']
