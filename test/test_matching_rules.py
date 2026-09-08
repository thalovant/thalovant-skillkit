"""How a term matches is a fact about a language, and lives in locale/.

`WORDLESS_SCRIPTS = {"ja","ko","th","zh"}` and `_INFLECTION = r"\\w{0,3}"` were
written into vocab.py, which made two language facts invisible to anyone
reading the locale tree and applied an English-and-French assumption -- that an
inflection adds at most three letters -- to all 47 locales the fleet serves.
"""
from __future__ import annotations

import json

import pytest

from thalovant_skillkit import contains_term, is_wordless, matching_rules
from thalovant_skillkit.vocab import LOCALE_DIR, available_langs


def test_every_bundled_locale_declares_a_usable_rule():
    langs = available_langs()

    assert "en-US" in langs, "en-US is the fallback every other language inherits"
    for lang in langs:
        rules = json.loads((LOCALE_DIR / lang / "matching.json").read_text(encoding="utf-8"))
        assert isinstance(rules["word_separated"], bool), lang
        assert isinstance(rules["inflection_max"], int), lang
        assert rules["inflection_max"] >= 0, lang


@pytest.mark.parametrize("lang", ["ja-JP", "ko-KR", "th-TH", "zh-CN", "zh-TW"])
def test_languages_written_without_spaces_match_by_containment(lang):
    """A word boundary means nothing where words are not separated."""
    assert is_wordless(lang)
    assert contains_term("今日のニュース", "ニュース", lang)


def test_a_space_separated_language_does_not_match_inside_a_word():
    assert not is_wordless("en-US")
    assert not contains_term("technology", "log", "en-US")
    assert not contains_term("今日のニュース", "ニュース", "en-US")


def test_the_bound_is_per_language_even_though_only_english_needs_one_today():
    """The mechanism is here so a language that needs a different bound can say
    so in its own file. No such number is shipped: Turkish, Finnish and
    Hungarian stack suffixes and three letters is plainly too tight for them
    ("ev" -> "evlerimiz" is seven), but picking the right number is a claim
    about a language, and inventing one is how a made-up `ovos-utils>=0.3.0`
    floor got shipped earlier. They inherit en-US until someone who knows
    measures it.
    """
    _, english = matching_rules("en-US")

    assert english == 3
    assert matching_rules("tr-TR") == matching_rules("en-US")
    assert not contains_term("evlerimiz nerede", "ev", "tr-TR")


def test_an_unlisted_language_inherits_english():
    """The fleet serves 47 locales and only a few need their own rule, so a
    language with no file of its own falls back the way a skill's locale does."""
    assert matching_rules("de-DE") == matching_rules("en-US")
    assert matching_rules("pt-BR") == matching_rules("en-US")
    assert matching_rules(None) == matching_rules("en-US")


def test_a_regional_variant_uses_its_languages_rule():
    assert matching_rules("fr-CA") == matching_rules("fr-FR")
    assert is_wordless("zh-Hant-TW")


def test_the_rules_are_read_from_the_files_not_hardcoded():
    """Changing a shipped file changes the behaviour -- which is the point of
    moving it out of Python."""
    from thalovant_skillkit import vocab

    vocab.matching_rules.cache_clear()
    for lang in available_langs():
        shipped = json.loads((LOCALE_DIR / lang / "matching.json").read_text(encoding="utf-8"))
        assert matching_rules(lang) == (shipped["word_separated"], shipped["inflection_max"])
