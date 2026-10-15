"""Telling the visitor where a slow lookup is going, once, and only when it is slow."""
import time

import pytest

from thalovant_skillkit import knowledge
from thalovant_skillkit.knowledge import lookup_notice, notice_text, run_noticing


def slow(seconds, value="answer"):
    def work():
        time.sleep(seconds)
        return value
    return work


def test_a_quick_lookup_says_nothing():
    said = []
    with lookup_notice(said.append) as notice:
        assert run_noticing(slow(0), lang="en-US", mode="answer", delay=0.3) == "answer"
    assert said == [] and not notice.named


def test_a_slow_lookup_says_where_it_is_looking_while_it_carries_on():
    said = []
    with lookup_notice(said.append) as notice:
        started = time.monotonic()
        result = run_noticing(slow(0.5), lang="en-US", mode="answer", delay=0.1)
        elapsed = time.monotonic() - started
    assert result == "answer"
    assert said == ["Checking Wikipedia and DuckDuckGo…"]
    # the lookup was not restarted or serialized behind the notice
    assert elapsed < 0.9
    assert notice.names("wikipedia") and notice.names("DuckDuckGo") and notice.names("web-search")
    assert not notice.names("wikidata") and not notice.names("wolfram")


def test_the_notice_is_said_once_however_many_lookups_a_turn_makes():
    said = []
    with lookup_notice(said.append):
        for _ in range(3):
            run_noticing(slow(0.3), lang="en-US", mode="answer", delay=0.05)
    assert len(said) == 1


def test_a_notice_open_for_one_turn_does_not_reach_the_next():
    first, second = [], []
    with lookup_notice(first.append):
        run_noticing(slow(0.2), lang="en-US", mode="answer", delay=0.05)
    with lookup_notice(second.append):
        run_noticing(slow(0.2), lang="en-US", mode="answer", delay=0.05)
    assert len(first) == len(second) == 1


def test_without_a_notice_the_lookup_just_runs():
    assert run_noticing(slow(0.2), lang="en-US", mode="answer", delay=0.01) == "answer"


def test_research_names_the_papers_it_asks_too():
    text, named = notice_text("en-US", "research")
    assert text == "Checking Wikipedia, DuckDuckGo, OpenAlex, Crossref, and arXiv…"
    assert named == {"wikipedia", "duckduckgo", "openalex", "crossref", "arxiv"}


@pytest.mark.parametrize("lang,start", [
    ("fr-FR", "Je consulte Wikipedia et DuckDuckGo"),
    ("fr-CA", "Je consulte Wikipedia et DuckDuckGo"),
    ("es-ES", "Consultando Wikipedia y DuckDuckGo"),
    ("de-DE", "Ich frage Wikipedia und DuckDuckGo ab"),
    ("it-IT", "Consulto Wikipedia e DuckDuckGo"),
    ("pt-PT", "A consultar Wikipedia e DuckDuckGo"),
    ("nl-NL", "Ik raadpleeg Wikipedia en DuckDuckGo"),
    ("ca-ES", "Consultant Wikipedia i DuckDuckGo"),
    ("gl-ES", "Consultando Wikipedia e DuckDuckGo"),
    ("eu-ES", "Wikipedia eta DuckDuckGo kontsultatzen"),
    ("hi-IN", "Wikipedia और DuckDuckGo में देखा जा रहा है"),
])
def test_the_official_hub_languages_each_have_their_own_line(lang, start):
    assert notice_text(lang, "answer")[0].startswith(start)


def test_a_language_without_a_line_uses_english_and_a_bad_tag_does_not_break_it():
    assert notice_text("ja-JP", "answer")[0] == "Checking Wikipedia and DuckDuckGo…"
    assert notice_text("not a tag", "answer")[0] == "Checking Wikipedia and DuckDuckGo…"
    assert notice_text(None, "answer")[0] == "Checking Wikipedia and DuckDuckGo…"


def test_the_shared_client_notices_a_slow_service(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"text": "Ada Lovelace was a mathematician.", "augmented": False}

    def post(url, **kwargs):
        time.sleep(0.4)
        return Response()

    monkeypatch.setattr(knowledge.requests, "post", post)
    monkeypatch.setattr(knowledge, "NOTICE_DELAY", 0.05)
    said = []
    with lookup_notice(said.append):
        reply = knowledge.knowledge_reply(
            service_url="http://knowledge", prompt="who was ada lovelace", lang="en-US",
            mode="answer", max_sources=2, augmentation="auto", age_policy_setting=None,
            headers={}, timeout=5)
    assert reply.answer == "Ada Lovelace was a mathematician."
    assert said == ["Checking Wikipedia and DuckDuckGo…"]
