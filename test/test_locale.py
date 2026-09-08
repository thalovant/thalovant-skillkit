"""A skill's locale/ tree, against a real one built in a temp directory."""
from __future__ import annotations

import pytest

from thalovant_skillkit import SkillResources


@pytest.fixture
def resources(tmp_path):
    for lang, vocab, dialog in (
        ("en-US", "news\nheadlines\n# a comment\n\nnews briefing\n", "The news is {what}.\n"),
        ("fr-FR", "nouvelles\nactualites\n", "Les nouvelles : {what}.\n"),
    ):
        (tmp_path / lang / "vocab").mkdir(parents=True)
        (tmp_path / lang / "dialog").mkdir(parents=True)
        (tmp_path / lang / "vocab" / "NewsKeyword.voc").write_text(vocab, encoding="utf-8")
        (tmp_path / lang / "dialog" / "news.dialog").write_text(dialog, encoding="utf-8")
    # A vocabulary only English has, to exercise the fallback.
    (tmp_path / "en-US" / "vocab" / "OnlyEnglish.voc").write_text("umbrella\n", encoding="utf-8")
    return SkillResources(tmp_path)


def test_it_serves_the_closest_bundled_language(resources):
    assert resources.lang("fr-FR") == "fr-FR"
    assert resources.lang("fr-CA") == "fr-FR"      # same language, other region
    assert resources.lang("de-DE") == "en-US"      # nothing close: English
    assert resources.lang(None) == "en-US"


def test_comments_and_blank_lines_are_not_vocabulary(resources):
    assert resources.vocab("NewsKeyword", "en-US") == ("news", "headlines", "news briefing")


def test_a_missing_translation_falls_back_to_english(resources):
    """Answering in the wrong language beats going silent, so a vocabulary the
    translation has not reached yet still matches through English."""
    assert resources.voc_match("OnlyEnglish", "do I need an umbrella", "fr-FR")
    assert resources.voc_match_lang("OnlyEnglish", "do I need an umbrella", "fr-FR") == "en-US"


def test_matching_uses_the_word_start_rule(resources):
    """The whole point of routing this through the library: a `.voc` line is
    not allowed to claim a word that merely spells it."""
    assert resources.voc_match("NewsKeyword", "what is the news", "en-US")
    assert resources.voc_match("NewsKeyword", "give me the headlines", "en-US")
    assert not resources.voc_match("NewsKeyword", "renews the subscription", "en-US")


def test_the_matching_term_comes_back_longest_first(resources):
    assert resources.voc_term("NewsKeyword", "play the news briefing", "en-US") == "news briefing"
    assert resources.voc_term("NewsKeyword", "nothing here", "en-US") == ""


def test_dialog_renders_and_survives_a_missing_file(resources):
    assert resources.dialog("news", "en-US", {"what": "quiet"}) == "The news is quiet."
    assert resources.dialog("news", "fr-FR", {"what": "calme"}) == "Les nouvelles : calme."
    # A missing translation should sound wrong, not crash mid-answer.
    assert resources.dialog("absent", "en-US") == "absent"
    assert resources.dialog("news", "en-US") == "The news is {what}."


def test_two_skills_do_not_share_a_cache(tmp_path):
    """The lookup is cached per instance. Keyed on the language alone it would
    hand one skill the other skill's locale."""
    for name, word in (("a", "alpha"), ("b", "beta")):
        (tmp_path / name / "en-US" / "vocab").mkdir(parents=True)
        (tmp_path / name / "en-US" / "vocab" / "K.voc").write_text(word, encoding="utf-8")
    first, second = SkillResources(tmp_path / "a"), SkillResources(tmp_path / "b")
    assert first.vocab("K", "en-US") == ("alpha",)
    assert second.vocab("K", "en-US") == ("beta",)


def test_an_absent_locale_tree_is_empty_not_an_error(tmp_path):
    resources = SkillResources(tmp_path / "nothing-here")
    assert resources.available_langs() == ()
    assert resources.vocab("K", "en-US") == ()
    assert not resources.voc_match("K", "anything", "en-US")
