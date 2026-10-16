"""Telling the visitor which source is answering, once, and only when the answer is slow."""
import contextlib
import json
import time

import pytest
import requests

from thalovant_skillkit import knowledge
from thalovant_skillkit.knowledge import (
    ask_service,
    current_notice,
    knowledge_reply,
    lookup_notice,
    notice_text,
    provider_name,
)

SOURCE = {"event": "source", "provider": "wikipedia"}
ANSWER = {"text": "Ada Lovelace was a mathematician.", "provider": "wikipedia", "augmented": True}


class Streamed:
    """A streaming response: the lines arrive when `delays` say they do."""

    def __init__(self, events, delays=None):
        self.events = events
        self.delays = delays or [0] * len(events)
        self.status_code = 200
        self.headers = {"Content-Type": "application/x-ndjson"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self, decode_unicode=False):
        for event, delay in zip(self.events, self.delays, strict=True):
            time.sleep(delay)
            yield json.dumps(event)


class Plain:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


@pytest.fixture
def served(monkeypatch):
    """Install a fake `requests.post`; returns the calls it was given."""
    calls = []

    def install(response):
        def post(url, **kwargs):
            calls.append((url, kwargs))
            return response

        monkeypatch.setattr(knowledge.requests, "post", post)
        monkeypatch.setattr(knowledge, "NOTICE_DELAY", 0.1)

    install.calls = calls
    return install


def ask(lang="en-US"):
    return ask_service(service_url="http://knowledge", request_payload={"prompt": "ada"},
                       headers={"X-Skill": "t"}, timeout=5, lang=lang)


def test_a_slow_answer_says_the_exact_source_and_then_the_answer_arrives(served):
    served(Streamed([SOURCE, {"event": "answer", "answer": ANSWER}], [0, 0.4]))
    said = []
    with lookup_notice(said.append) as notice:
        assert ask() == ANSWER
    assert said == ["From Wikipedia…"]
    assert notice.names("wikipedia") and not notice.names("duckduckgo")


def test_an_answer_that_follows_the_source_at_once_says_nothing(served):
    served(Streamed([SOURCE, {"event": "answer", "answer": ANSWER}]))
    said = []
    with lookup_notice(said.append) as notice:
        assert ask() == ANSWER
    assert said == [] and not notice.named


def test_a_service_that_does_not_stream_is_read_as_plain_json(served):
    served(Plain(ANSWER))
    said = []
    with lookup_notice(said.append):
        assert ask() == ANSWER
    assert said == []
    url, kwargs = served.calls[0]
    assert url == "http://knowledge/v1/knowledge/answer"
    assert kwargs["headers"]["Accept"].startswith("application/x-ndjson")
    assert kwargs["headers"]["X-Skill"] == "t"


def test_without_a_notice_the_request_is_the_plain_one_it_always_was(served):
    served(Plain(ANSWER))
    assert ask() == ANSWER
    _, kwargs = served.calls[0]
    assert kwargs["headers"] == {"X-Skill": "t"} and "stream" not in kwargs
    assert kwargs["json"] == {"prompt": "ada"} and kwargs["timeout"] == 5


def test_the_notice_is_said_once_however_many_lookups_a_turn_makes(served):
    served(Streamed([SOURCE, {"event": "answer", "answer": ANSWER}], [0, 0.3]))
    said = []
    with lookup_notice(said.append):
        ask()
        ask()
    assert said == ["From Wikipedia…"]


def test_each_turn_has_its_own_notice(served):
    served(Streamed([SOURCE, {"event": "answer", "answer": ANSWER}], [0, 0.3]))
    first, second = [], []
    with lookup_notice(first.append):
        ask()
    with lookup_notice(second.append):
        ask()
    assert first == second == ["From Wikipedia…"]
    assert current_notice() is None


def test_an_error_after_the_source_is_the_status_the_plain_reply_would_have_had(served):
    served(Streamed([SOURCE, {"event": "error", "status": 404, "detail": "no answer"}]))
    with lookup_notice([].append), pytest.raises(requests.HTTPError) as caught:
        ask()
    assert caught.value.response.status_code == 404


def test_a_stream_that_ends_without_an_answer_is_an_error_not_a_hang(served):
    served(Streamed([SOURCE]))
    with lookup_notice([].append), pytest.raises(ValueError):
        ask()


def test_a_notice_that_cannot_be_said_does_not_cost_the_answer(served, caplog):
    served(Streamed([SOURCE, {"event": "answer", "answer": ANSWER}], [0, 0.3]))

    def broken(text):
        raise RuntimeError("the client went away")

    with lookup_notice(broken):
        assert ask() == ANSWER
    assert "Could not say where the answer comes from" in caplog.text


def test_a_source_that_answers_without_an_announcement_says_nothing(served):
    served(Streamed([{"event": "answer", "answer": ANSWER}]))
    said = []
    with lookup_notice(said.append):
        assert ask() == ANSWER
    assert said == []


def test_the_shared_client_uses_it_so_every_skill_behaves_alike(served):
    served(Streamed([SOURCE, {"event": "answer", "answer": ANSWER}], [0, 0.3]))
    said = []
    with lookup_notice(said.append):
        reply = knowledge_reply(
            service_url="http://knowledge", prompt="who was ada lovelace", lang="en-US",
            mode="answer", max_sources=2, augmentation="auto", age_policy_setting=None,
            headers={}, timeout=5)
    assert reply.answer == ANSWER["text"] and reply.augmented
    assert said == ["From Wikipedia…"]


def test_a_404_from_a_streaming_service_is_still_no_answer(served):
    served(Streamed([SOURCE, {"event": "error", "status": 404, "detail": "none"}]))
    with lookup_notice([].append):
        reply = knowledge_reply(
            service_url="http://knowledge", prompt="x", lang="en-US", mode="answer", max_sources=1,
            augmentation="auto", age_policy_setting=None, headers={}, timeout=5)
    assert reply.answer is None and reply.policy == knowledge.POLICY_NO_ANSWER


@pytest.mark.parametrize("lang,line", [
    ("en-US", "From Wikipedia…"),
    ("fr-FR", "Selon Wikipedia…"),
    ("fr-CA", "Selon Wikipedia…"),
    ("es-ES", "Según Wikipedia…"),
    ("de-DE", "Laut Wikipedia…"),
    ("it-IT", "Secondo Wikipedia…"),
    ("pt-PT", "Segundo Wikipedia…"),
    ("nl-NL", "Volgens Wikipedia…"),
    ("ca-ES", "Segons Wikipedia…"),
    ("gl-ES", "Segundo Wikipedia…"),
    ("eu-ES", "Iturria: Wikipedia…"),
    ("hi-IN", "Wikipedia से…"),
    ("ja-JP", "From Wikipedia…"),
    ("not a tag", "From Wikipedia…"),
    (None, "From Wikipedia…"),
])
def test_the_official_hub_languages_each_have_their_own_line(lang, line):
    assert notice_text(lang, "wikipedia") == line


def test_a_provider_is_named_the_way_a_visitor_knows_it():
    ids = ("wikipedia", "web-search", "wolfram", "arxiv", "wikihow")
    assert [provider_name(p) for p in ids] == [
        "Wikipedia", "DuckDuckGo", "WolframAlpha", "arXiv", "wikiHow"]
    assert provider_name("semantic_scholar") == "Semantic Scholar"
    assert provider_name("some-new-provider") == "Some New Provider"


def test_the_service_name_for_a_source_counts_as_the_same_source():
    with lookup_notice([].append) as notice:
        notice.named = frozenset({"duckduckgo"})
        assert notice.names("web-search") and notice.names("DuckDuckGo")
        notice.named = frozenset({"wolfram"})
        assert notice.names("wolframalpha")
        assert not notice.names("wikipedia")


def test_run_noticing_from_0_26_still_runs_the_work():
    with lookup_notice([].append):
        assert knowledge.run_noticing(lambda: 7, lang="en-US", mode="answer") == 7


def test_a_skill_can_read_the_turns_notice_and_there_is_none_outside_a_turn():
    assert current_notice() is None
    with contextlib.ExitStack() as stack:
        notice = stack.enter_context(lookup_notice([].append))
        assert current_notice() is notice
    assert current_notice() is None


class Lines:
    """Raw lines, as a service might send them, and whether the reader went past the first."""

    status_code = 200
    headers = {"Content-Type": "application/x-ndjson"}

    def __init__(self, lines, hang_after_first=False):
        self.lines, self.hang_after_first, self.read = lines, hang_after_first, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self, decode_unicode=False):
        for index, line in enumerate(self.lines):
            if index and self.hang_after_first:
                time.sleep(30)
            self.read = index + 1
            yield line


@pytest.mark.parametrize("line", [
    "[]", '"x"', "null", "7", '{"no":"event"}', '{"event":3}', "not json at all",
    '{"event":"source"}', '{"event":"source","provider":4}',
    '{"event":"answer"}', '{"event":"answer","answer":"text"}', '{"event":"answer","answer":[1]}',
    '{"event":"error"}', '{"event":"error","status":"404","detail":"x"}',
    '{"event":"error","status":404}',
])
def test_a_malformed_stream_line_is_a_failed_request_not_a_crash(served, line):
    served(Lines([line]))
    with lookup_notice([].append), pytest.raises(ValueError):
        ask()


def test_the_shared_client_turns_a_malformed_line_into_an_unavailable_answer(served):
    served(Lines(['{"event":"answer","answer":"text"}']))
    with lookup_notice([].append):
        reply = knowledge_reply(
            service_url="http://knowledge", prompt="x", lang="en-US", mode="answer", max_sources=1,
            augmentation="auto", age_policy_setting=None, headers={}, timeout=5)
    assert reply.answer is None and reply.policy == knowledge.POLICY_NONE


def test_an_answer_that_comes_first_is_returned_without_waiting_for_the_stream_to_end(served):
    response = Lines([json.dumps({"event": "answer", "answer": ANSWER}), json.dumps(SOURCE)],
                     hang_after_first=True)
    served(response)
    started = time.monotonic()
    with lookup_notice([].append):
        assert ask() == ANSWER
    assert time.monotonic() - started < 5 and response.read == 1


def test_an_error_that_comes_first_is_raised_without_waiting_for_the_stream_to_end(served):
    response = Lines([json.dumps({"event": "error", "status": 404, "detail": "none"}),
                      json.dumps(SOURCE)], hang_after_first=True)
    served(response)
    started = time.monotonic()
    with lookup_notice([].append), pytest.raises(requests.HTTPError):
        ask()
    assert time.monotonic() - started < 5 and response.read == 1
