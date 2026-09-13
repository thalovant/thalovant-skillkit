"""Fallback matching for concrete packaged phrases, without pattern expansion."""
import pytest

from thalovant_skillkit.locale import SkillResources


@pytest.fixture
def resources(tmp_path):
    for locale, folder, text in (
        ("en-US", "", "Translate this\n# comment\nshow {item}\nplay (a|the) song\n[please] stop\n"),
        ("fr-FR", "", "Checklist de sécurité\nDonne-moi une idée\n"),
        ("fr-FR", "intents", "Traduis ceci\n"),
        ("ja-JP", "", "これを翻訳して\n"),
    ):
        path = tmp_path / locale / folder / "demo.intent"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return SkillResources(tmp_path)


def test_complete_normalized_phrase_and_nested_layout(resources):
    assert resources.matches_literal_intent(" Checklist DE SÉCURITÉ! ", "demo", "fr-FR")
    assert resources.matches_literal_intent("donne moi une idée", "demo.intent", "fr-FR")
    assert resources.matches_literal_intent("traduis ceci", "demo", "fr-CA")
    assert resources.matches_literal_intent("これを翻訳して。", "demo", "ja-JP")


@pytest.mark.parametrize("utterance", [
    "checklist", "do not translate this", "", "!!!", "Translate this and that",
])
def test_partial_or_negated_phrase_does_not_match(resources, utterance):
    assert not resources.matches_literal_intent(utterance, "demo", "en-US")


@pytest.mark.parametrize("utterance", [
    "show item", "show {item}", "play a song", "play a the song", "please stop",
])
def test_pattern_lines_are_never_treated_as_literal_phrases(resources, utterance):
    assert not resources.matches_literal_intent(utterance, "demo", "en-US")


def test_matching_does_not_merge_supported_languages(resources):
    assert not resources.matches_literal_intent("translate this", "demo", "fr-FR")
    assert not resources.matches_literal_intent("traduis ceci", "demo", "en-US")
    assert not resources.matches_literal_intent("translate this", "missing", "en-US")
    assert resources.matches_literal_intent("translate this", "demo", "xx-XX")


def test_literal_cache_belongs_to_each_resource_tree(resources, tmp_path):
    assert resources.matches_literal_intent("translate this", "demo", "en-US")
    other = SkillResources(tmp_path / "different-skill")
    assert not other.matches_literal_intent("translate this", "demo", "en-US")
