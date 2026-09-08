"""The rule that was wrong in five skills at once."""
from __future__ import annotations

import pytest

from thalovant_skillkit import contains_term, first_match, matches_any


@pytest.mark.parametrize(
    "text, term, why",
    [
        ("what's the latest news about technology", "log", "the measured bug"),
        ("des nouvelles sur la technologie", "log", "and in French"),
        ("write me an apology", "log", "apology"),
        ("show me the news catalog", "log", "catalog"),
        ("play a podcast", "pod", "podcast"),
        ("ou trouver un eclair", "clair", "eclair"),
        ("pourquoi le ciel est bleu", "quoi", "pourquoi"),
        ("fill in the questionnaire", "question", "questionnaire"),
        ("toutefois je ne sais pas", "fois", "toutefois"),
    ],
)
def test_a_term_does_not_claim_a_word_that_merely_spells_it(text, term, why):
    """ops-copilot's logs.voc holds the line `log`; "technology" spells it at
    position six. With plain containment the ops copilot answered "what's the
    latest news about technology" with "Paste events or logs." -- in a real
    ovos-core, in both languages, because thalovant-skill-news registers no
    fallback and nothing behind it could correct the answer."""
    assert not contains_term(text, term), why


@pytest.mark.parametrize(
    "text, term",
    [
        ("explain these logs", "log"),
        ("why are my pods crashing", "pod"),
        ("summarize the incidents from last night", "incident"),
        ("rends ces messages plus clairs", "message"),
        ("rends ces messages plus clairs", "clair"),
        ("peux-tu m'expliquer", "explique"),
        ("quelle heure est-il", "quel"),
        ("explain this log line", "log"),
    ],
)
def test_a_term_still_claims_its_own_inflections(text, term):
    """Anchoring both ends of the term is the obvious fix and it breaks these:
    the vocabularies list the singular and rely on it catching the plural. That
    is why three trailing letters are allowed rather than none."""
    assert contains_term(text, term)


def test_languages_without_word_spacing_keep_containment():
    """A word boundary means nothing in Japanese, Korean, Thai or Chinese."""
    assert contains_term("今日のニュース", "ニュース", "ja-JP")
    assert not contains_term("今日のニュース", "ニュース", "en-US")


def test_an_empty_term_or_text_claims_nothing():
    assert not contains_term("", "log")
    assert not contains_term("explain these logs", "")


def test_the_longest_matching_term_wins():
    """"news briefing" and "news" both match; the specific one is the answer."""
    assert first_match("play the news briefing", ["news", "news briefing"]) == "news briefing"
    assert first_match("nothing here", ["news"]) == ""
    assert matches_any("explain these logs", ["nope", "log"])
