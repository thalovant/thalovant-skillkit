"""Shared plumbing for the Thalovant OVOS skills.

Twenty-three skills grew the same handful of private helpers independently.
An audit across the fleet found 36 functions living in three or more skills --
about 1,600 duplicated lines -- and, more to the point, that they had drifted:
`_message_lang` existed in eighteen skills in ten different shapes, and the
thin ones simply read fewer places and were wrong more often.

Drift is not a tidiness problem. Five skills matched their vocabularies with
`term in text`, so ops-copilot's `log` matched "technology" and the ops copilot
answered "what's the latest news about technology". Fixing that meant the same
edit in five repositories, and the sixth skill would have inherited the bug.

What is here is what more than one skill already had, reconciled to the
behaviour of the most careful copy:

    message    reading utterance, language, session and location off a Message
    text       folding text so a vocabulary line and a spoken phrase compare
    vocab      whether an utterance contains a term, without claiming "podcast"
    locale     a skill's own locale/ tree: language choice, lines, dialog, voc
    fallback   the ladder rung, an operator override, registering once
    service    request headers with a traceable id, and a POST that stays quiet
    knowledge  the knowledge-service client, previously vendored three times

Three more modules are not imported here, because each stands on its own:
`skill` carries base classes that hold a skill's plumbing and needs
ovos-workshop (`pip install thalovant-skillkit[skill]`); `testing` builds the
message doubles skill tests keep reinventing; `checks` is what every skill's CI
runs -- a locale contract that was vendored into fifteen skills byte for byte,
plus the packaging mistakes that read as a broken skill. `thalovant-skillkit
new` writes a skill that passes all of it, and `thalovant-skillkit check` runs
it on any skill.

How a term may match is a fact about a language, not about this code, so it
lives in locale/<lang>/matching.json beside everything else the fleet keeps
per language -- not in a set of language codes written into vocab.py.
"""
from __future__ import annotations

from .fallback import LOW_BAND, register_once, resolve_priority
from .locale import DEFAULT_LANG, SkillResources
from .message import (
    context_of,
    context_value,
    data_of,
    location,
    message_lang,
    session_of,
    standardize,
    utterance,
    utterances,
)
from .service import post_json, request_headers
from .text import fold, fold_spaces, fold_tight, fold_words, strip_accents
from .version import __version__
from .vocab import (
    available_langs,
    contains_term,
    first_match,
    is_wordless,
    matches_any,
    matching_rules,
    term_pattern,
)

__all__ = [
    "DEFAULT_LANG",
    "LOW_BAND",
    "SkillResources",
    "__version__",
    "available_langs",
    "contains_term",
    "context_of",
    "context_value",
    "data_of",
    "first_match",
    "fold",
    "fold_spaces",
    "fold_tight",
    "fold_words",
    "is_wordless",
    "location",
    "matches_any",
    "matching_rules",
    "message_lang",
    "post_json",
    "register_once",
    "request_headers",
    "resolve_priority",
    "session_of",
    "standardize",
    "strip_accents",
    "term_pattern",
    "utterance",
    "utterances",
]
