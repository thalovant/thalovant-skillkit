"""Reading a bus message, at the thoroughness the most careful skill had."""
from __future__ import annotations

import pytest

from thalovant_skillkit import (
    context_value,
    location,
    message_lang,
    standardize,
    utterance,
    utterances,
)


class Msg:
    def __init__(self, data=None, context=None):
        self.data = data or {}
        self.context = context or {}


def test_the_utterance_is_read_from_every_key_a_message_uses():
    """`utterance` is what the intent pipeline sends; `phrase`, `text` and
    `query` arrive from OCP search, converse and the showroom preview. Fifteen
    skills read only the first and went quiet on the other three paths."""
    assert utterance(Msg({"utterance": " turn it up "})) == "turn it up"
    assert utterance(Msg({"phrase": "a podcast"})) == "a podcast"
    assert utterance(Msg({"text": "some text"})) == "some text"
    assert utterance(Msg({"query": "a query"})) == "a query"
    assert utterance(Msg({"utterances": ["", "  second best  "]})) == "second best"


def test_an_empty_message_yields_an_empty_string_not_an_error():
    assert utterance(Msg()) == ""
    assert utterance(Msg({"utterance": "   "})) == ""
    assert utterance(object()) == ""


def test_every_phrasing_is_available_in_order_without_duplicates():
    message = Msg({"utterance": "one", "utterances": ["one", "two"]})
    assert utterances(message) == ["one", "two"]


@pytest.mark.parametrize(
    "message, expected",
    [
        (Msg(data={"lang": "fr-FR"}), "fr-FR"),
        (Msg(context={"lang": "fr-FR"}), "fr-FR"),
        (Msg(context={"session": {"lang": "fr-FR"}}), "fr-FR"),
        # data wins over context, context over session: the satellite stamps the
        # language of *this* utterance on the data, while the session carries
        # the hub's standing default.
        (Msg(data={"lang": "fr-FR"}, context={"lang": "en-US"}), "fr-FR"),
        (Msg(context={"lang": "fr-FR", "session": {"lang": "en-US"}}), "fr-FR"),
    ],
)
def test_the_language_is_looked_for_in_all_three_places(message, expected):
    """Five skills read only `context["lang"]`, so an utterance carrying its
    language in the data or the session was answered in the wrong one."""
    assert message_lang(message, "en-US") == expected


def test_the_language_falls_back_to_the_skills_own():
    assert message_lang(Msg(), "fr-FR") == "fr-FR"
    assert message_lang(Msg(), "") == "en-US"


def test_a_language_tag_is_normalised_however_it_was_written():
    assert standardize("fr_fr") == "fr-FR"
    assert standardize("EN-us") == "en-US"
    assert standardize(None) == "en-US"


def test_the_location_comes_back_only_when_it_is_really_there():
    """Without the house's location OVOS answers from its own default --
    Lawrence, Kansas -- so date-time reports the wrong hour and weather the
    wrong city. A malformed value has to read as absent, not as a location."""
    montreal = {"city": {"name": "Montreal"}}
    assert location(Msg(context={"location": montreal})) == montreal
    assert location(Msg(data={"location": montreal})) == montreal
    assert location(Msg()) is None
    assert location(Msg(context={"location": "Montreal"})) is None


def test_context_value_prefers_context_then_data_and_skips_empties():
    message = Msg(data={"site_id": "kitchen"}, context={"site_id": ""})
    assert context_value(message, "site_id") == "kitchen"
    assert context_value(message, "nothing", default="fallback") == "fallback"


@pytest.mark.parametrize(
    "tag, expected",
    [
        ("fr_fr", "fr-FR"),
        ("fr-FR", "fr-FR"),
        ("FR-fr", "fr-FR"),
        ("en_US", "en-US"),
        ("en-us", "en-US"),
        ("fr", "fr"),
    ],
)
def test_the_tag_shape_does_not_depend_on_which_ovos_version_is_installed(tag, expected):
    """ovos-utils 0.8.5 -- the floor the skills themselves declare -- strips the
    region ("en-us" -> "en", "FR-fr" -> "fr") and leaves an underscore alone
    ("fr_fr" -> "fr_fr"). 0.14 returns "en-US" and "fr-FR". Resolving "fr_fr"
    against the older one found no `fr_fr` locale directory, split on "-" to get
    a primary of "fr_fr", matched nothing, and served French in English.

    This ran green for a while because the test environment has no ovos-utils
    at all and fell back to the local canonicaliser, so the assertion only ever
    exercised the fallback. It now pins the result of whichever normaliser is
    actually installed.
    """
    assert standardize(tag) == expected


def test_a_skill_resolves_its_french_locale_from_any_spelling(tmp_path):
    """The failure this prevents, at the level where it was visible."""
    from thalovant_skillkit import SkillResources

    for lang in ("en-US", "fr-FR"):
        (tmp_path / lang / "vocab").mkdir(parents=True)
    resources = SkillResources(tmp_path)

    for spelling in ("fr-FR", "fr_fr", "FR-fr", "fr"):
        assert resources.lang(spelling) == "fr-FR", spelling


@pytest.mark.parametrize(
    "tag, expected",
    [
        ("zh-Hant-TW", "zh-Hant-TW"),   # language-script-region
        ("zh_hant_tw", "zh-Hant-TW"),
        ("es-419", "es-419"),           # a numeric region
        ("pt-BR", "pt-BR"),
    ],
)
def test_a_script_subtag_is_not_mistaken_for_a_region(tag, expected):
    """Upper-casing the second part regardless turned "zh-Hant-TW" into
    "zh-HANT" and dropped the region -- caught by source-scout's locale test,
    which drives every bundled language through the knowledge service and
    checks the tag it sends."""
    assert standardize(tag) == expected
