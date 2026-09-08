"""Talking to a service, and staying quiet when it does not answer."""
from __future__ import annotations

from thalovant_skillkit import post_json, request_headers


def test_every_call_carries_an_id_the_service_logs_can_be_searched_by():
    headers = request_headers("thalovant-skill-news", "1.2.3", "news/1.2.3")

    assert headers["X-Thalovant-Skill"] == "thalovant-skill-news"
    assert headers["X-Thalovant-Skill-Version"] == "1.2.3"
    assert headers["User-Agent"] == "news/1.2.3"
    assert headers["X-Request-ID"].startswith("thalovant-skill-news-")


def test_two_calls_do_not_share_a_request_id():
    first = request_headers("s", "1", "u")["X-Request-ID"]
    second = request_headers("s", "1", "u")["X-Request-ID"]
    assert first != second


class Response:
    def __init__(self, payload=None, error=None):
        self._payload, self._error = payload, error

    def raise_for_status(self):
        if self._error:
            raise self._error

    def json(self):
        return self._payload


class Client:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), 0

    def post(self, url, json=None, timeout=None, headers=None):
        self.calls += 1
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_a_good_answer_comes_back_decoded():
    client = Client(Response({"answer": "yes"}))
    assert post_json("http://x/v1", {}, client=client) == {"answer": "yes"}
    assert client.calls == 1


def test_a_failed_call_is_retried_then_gives_up_quietly():
    """None rather than an exception, because every caller is inside a spoken
    reply: a skill that raises here says nothing at all."""
    client = Client(ConnectionError("down"), Response({"answer": "late"}))
    assert post_json("http://x/v1", {}, client=client, attempts=2) == {"answer": "late"}

    dead = Client(ConnectionError("down"), ConnectionError("still down"))
    assert post_json("http://x/v1", {}, client=dead, attempts=2) is None
    assert dead.calls == 2
