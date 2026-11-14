"""The connector spec's shared speech vectors: the hub-side cleaner (`clean_speech`) and this one
(`speakable`) are held to the same corpus. Read from an installed spec; skipped without it."""

import json
from importlib import resources

import pytest

from thalovant_skillkit.safety import speakable
from thalovant_skillkit.ssml import strip_tags


def _cases() -> list[dict]:
    try:
        text = (
            (resources.files("thalovant_connector_spec") / "vectors" / "speech.json")
            .read_text(encoding="utf-8")
        )
    except (ModuleNotFoundError, FileNotFoundError, OSError):
        return []
    return json.loads(text)["cases"]


CASES = _cases()


def test_the_vectors_were_found_or_this_run_says_why_it_skips():
    if not CASES:
        pytest.skip("thalovant-connector-spec is not installed (or ships no vectors/speech.json)")
    assert len(CASES) >= 27


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_speakable_gives_what_the_shared_vector_expects(case):
    assert speakable(case["input"], case.get("limit", 120)) == case["expect"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_strip_tags_never_returns_markup_for_any_vector(case):
    said = strip_tags(case["input"])
    assert "<" not in said and ">" not in said


def test_a_long_fold_is_bounded_after_it_not_only_before_it():
    """U+FDFA becomes eighteen characters under NFKC (82 ms in the spec): what is looked at stays
    within the read limit after each fold."""
    import time

    from thalovant_skillkit.safety import READ_AT_MOST

    started = time.perf_counter()
    for text in ("\ufdfa" * READ_AT_MOST, "&#xfdfa;" * 400 + "\ufdfa" * 2000):
        assert len(speakable(text, 100000)) <= READ_AT_MOST
        assert len(strip_tags(text)) <= READ_AT_MOST
    assert time.perf_counter() - started < 0.5


def test_a_mark_between_the_colon_and_the_slashes_still_breaks_the_address():
    assert speakable("see http:\u0338//evil.example/a now") == "see http \u0338 evil.example a now"
    assert "/" not in speakable("http:\u0301//x") and ":" not in speakable("http:\u0301//x")
    assert speakable("at 10:30 and a/b") == "at 10:30 and a/b"        # no address, nothing removed


def test_a_numeric_entity_with_thousands_of_digits_cannot_reach_the_int_limit():
    """int() refuses more than 4300 digits; the read limit (2400) keeps every entity below it."""
    hostile = "&#" + "9" * 5000
    assert len(speakable(hostile)) <= 120 and len(strip_tags(hostile)) <= 2400
