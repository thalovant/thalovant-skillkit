"""Regional folders are overrides, not copies of a language's translation."""
from pathlib import Path

import pytest

from thalovant_skillkit.locale import SkillResources
from thalovant_skillkit.message import message_lang, standardize
from thalovant_skillkit.testing import message


def write(root: Path, lang: str, filename: str, text: str) -> None:
    path = root / lang / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def resources(tmp_path):
    for tag in ("en-US", "en-CA", "fr-FR", "fr-CA", "pt-PT", "pt-BR",
                "nl-NL", "nl-BE", "sv-SE", "sv-FI", "zh-CN", "zh-TW", "sr-Latn", "sr-Cyrl"):
        write(tmp_path, tag, "dialog/place.dialog", tag)
    write(tmp_path, "fr-FR", "dialog/hello.dialog", "Bonjour {name}.")
    write(tmp_path, "en-US", "dialog/hello.dialog", "Hello {name}.")
    write(tmp_path, "fr-CA", "vocab/News.voc", "nouvelles")
    write(tmp_path, "fr-FR", "vocab/News.voc", "actualités")
    write(tmp_path, "en-US", "vocab/News.voc", "news")
    write(tmp_path, "fr-FR", "intents/news.intent", "donne les actualités")
    write(tmp_path, "fr-CA", "intents/news.intent", "donne les nouvelles")
    write(tmp_path, "en-US", "intents/news.intent", "give me the news")
    return SkillResources(tmp_path)


@pytest.mark.parametrize("tag,expected", [
    ("en", "en-US"), ("en-GB", "en-US"), ("en-AU", "en-US"),
    ("en-NZ", "en-US"), ("en-AQ", "en-US"), ("EN_ca", "en-CA"),
    ("fr", "fr-FR"), ("fr-BE", "fr-FR"), ("fr-CH", "fr-FR"), ("fr-WF", "fr-FR"),
    ("FR_ca", "fr-CA"), ("pt", "pt-PT"), ("pt-AO", "pt-PT"), ("pt-BR", "pt-BR"),
    ("nl", "nl-NL"), ("nl-SR", "nl-NL"), ("nl-BE", "nl-BE"),
    ("sv", "sv-SE"), ("sv-AX", "sv-SE"), ("sv-FI", "sv-FI"),
    ("zh-Hans-SG", "zh-CN"), ("zh-Hant-HK", "zh-TW"),
    ("sr-Latn-RS", "sr-Latn"), ("sr-Cyrl-RS", "sr-Cyrl"),
])
def test_reference_language_and_exact_regional_overrides(resources, tag, expected):
    assert resources.lang(tag) == expected
    assert resources.dialog("place", tag) == expected


def test_missing_regional_file_uses_french_before_english(resources):
    assert resources.candidate_langs("fr-CA") == ("fr-CA", "fr-FR", "en-US")
    assert resources.dialog("hello", "fr-CA", {"name": "Ada"}) == "Bonjour Ada."


def test_a_regional_override_does_not_hide_parent_vocabulary_or_intents(resources):
    for text in ("nouvelles", "actualités"):
        assert resources.voc_match("News", text, "fr-CA")
    for text in ("donne les nouvelles", "donne les actualités"):
        assert resources.matches_literal_intent(text, "news", "fr-CA")
    assert not resources.matches_literal_intent("give me the news", "news", "fr-CA")


def test_file_reads_remain_single_locale_unless_fallback_is_requested(resources):
    assert resources.vocab("News", "fr-CA") == ("nouvelles",)
    assert resources.lines("fr-CA", "dialog", "hello.dialog") == ()
    assert resources.lines("fr-CA", "dialog", "hello.dialog", fallback=True) == ("Bonjour {name}.",)


def test_explicit_script_is_not_silently_replaced(tmp_path):
    write(tmp_path, "zh-CN", "dialog/hello.dialog", "简体")
    write(tmp_path, "en-US", "dialog/hello.dialog", "Hello")
    resources = SkillResources(tmp_path)
    assert resources.lang("zh-Hant-TW") == "en-US"
    assert resources.lang("zh-SG") == "zh-CN"


def test_case_and_underscore_directory_names_resolve_to_the_actual_path(tmp_path):
    write(tmp_path, "fr_fr", "dialog/hello.dialog", "Bonjour")
    resources = SkillResources(tmp_path)
    assert resources.lang("FR-ca") == "fr_fr"
    assert resources.lang("fr-FR") == "fr_fr"
    assert resources.dialog("hello", "fr-CA") == "Bonjour"


def test_request_language_is_never_replaced_by_resource_language(resources):
    msg = message("bonjour", lang="FR_ch", session_id="kitchen")
    assert message_lang(msg) == "fr-CH"
    assert resources.lang(message_lang(msg)) == "fr-FR"
    assert message_lang(msg) == "fr-CH"


def test_configured_default_takes_precedence_over_reference_variety(tmp_path):
    write(tmp_path, "en-GB", "dialog/hello.dialog", "Hello from Britain")
    write(tmp_path, "en-US", "dialog/hello.dialog", "Hello from America")
    resources = SkillResources(tmp_path, default_lang="en-GB")
    assert resources.lang("en-AU") == "en-GB"
    assert resources.lang("en-US") == "en-US"


@pytest.mark.parametrize("tag", ["../../outside", "not a language", "en--CA"])
def test_malformed_requests_cannot_escape_the_bundled_resources(resources, tag):
    assert resources.lang(tag) in resources.available_langs()


@pytest.mark.parametrize("tag", ["en-GB-u-ca-gregory", "fr-CA-x-house", "zh-Hant"])
def test_structured_tags_keep_their_script_extensions_and_private_use(tag):
    assert standardize(tag) == tag
