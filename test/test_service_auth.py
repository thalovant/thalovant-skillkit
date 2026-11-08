"""The service token: to the platform's services, never anywhere else."""
from __future__ import annotations

import email.message
import io
import logging
import os
import urllib.request
import urllib.response

import pytest
import requests

from thalovant_skillkit import knowledge, post_json, request_headers, service_auth
from thalovant_skillkit.network import JsonServiceClient
from thalovant_skillkit.service_auth import (
    SERVICE_HOSTS,
    SERVICES,
    is_service_url,
    service_token,
    with_service_token,
)

TOKEN_A = "eyJhbGciOiJFZERTQSIsImtpZCI6ImEifQ.eyJzdWIiOiJydGc6YSJ9.c2lnbmF0dXJlLWE"
TOKEN_B = "eyJhbGciOiJFZERTQSIsImtpZCI6ImIifQ.eyJzdWIiOiJydGc6YSJ9.c2lnbmF0dXJlLWI"
LLM = "http://thalovant-llm.thalovant.svc.cluster.local:8080/v1/chat/completions"
WEATHER = "http://thalovant-weather-service.thalovant.svc.cluster.local:8080/v1/weather"
KNOWLEDGE = "http://thalovant-knowledge-service.thalovant.svc.cluster.local:8080"
EXTERNAL = "https://feeds.example.org/events.ics"

# Hosts an owner could type into a service_url, or that only look like ours.
NOT_OURS = [
    EXTERNAL,
    "http://example.com/v1/weather",
    "https://api.thalovant.com/v1/hubs",
    "https://tx.smartgic.io/translate",
    "http://thalovant-llm:8080/v1/models",  # bare: never ours from a runtime pod
    "http://thalovant-llm.evil.svc.cluster.local:8080/",
    "http://thalovant-llm.tenant-prod.svc.cluster.local:8080/",
    "http://thalovant-llm.thalovant.svc.cluster.local.evil.com/",
    "http://thalovant-llm.thalovant.svc.cluster.local.:8080@evil.com/",
    "http://thalovant-llm.thalovant.svc.cluster.local@evil.com/",
    "http://user:pw@thalovant-llm.thalovant.svc.cluster.local/",
    "http://evil.com\\@thalovant-llm.thalovant.svc.cluster.local/",
    "http://evil.com#@thalovant-llm.thalovant.svc.cluster.local/",
    "http://evil.com/?thalovant-llm.thalovant.svc.cluster.local",
    "http://evil.com/thalovant-llm.thalovant.svc.cluster.local",
    "http://thalovant-llm.thalovant.svc.cluster.local:99999/",
    "http://thalovant-llm.thalovant.svc.cluster.local /",
    "http://thalovant-llm.thalovant.svc.cluster.local\n/",
    "ftp://thalovant-llm.thalovant.svc.cluster.local/",
    "//thalovant-llm.thalovant.svc.cluster.local/",
    "thalovant-llm.thalovant.svc.cluster.local",
    "http://10.43.0.12:8080/",
    "http://thalovant-docs.thalovant.svc.cluster.local/",
    "http://thalovant-kube-inspector.thalovant.svc.cluster.local:8080/",
    "http://nllb.translator.svc.cluster.local:8000/",
    "http://localhost:8080/",
    "",
]


@pytest.fixture
def token(tmp_path, monkeypatch):
    """A token file where the operator puts it, rewritten the way the kubelet does."""
    monkeypatch.setattr(service_auth, "_TOKEN", service_auth.ServiceToken())
    path = tmp_path / "token"
    monkeypatch.setenv("THALOVANT_SERVICE_TOKEN_FILE", str(path))

    def write(value: str) -> None:
        staged = tmp_path / "token.next"
        staged.write_text(value)
        os.replace(staged, path)  # a new inode, as the atomic writer makes

    write(TOKEN_A + "\n")
    return write


@pytest.fixture
def no_token(tmp_path, monkeypatch):
    monkeypatch.setattr(service_auth, "_TOKEN", service_auth.ServiceToken())
    monkeypatch.setenv("THALOVANT_SERVICE_TOKEN_FILE", str(tmp_path / "absent" / "token"))


def _authorization(headers) -> list[str]:
    return [value for name, value in dict(headers).items() if name.lower() == "authorization"]


# --- where the token may go ---------------------------------------------------------


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize(
    "template",
    [
        "http://{s}.thalovant.svc.cluster.local:8080/v1/x",
        "https://{s}.thalovant.svc.cluster.local/v1/x",
        "http://{s}.thalovant.svc.cluster.local.:8080/",
        "http://{s}.thalovant.svc:8080",
        "http://{s}.thalovant:8080/",
        "HTTP://{S}.THALOVANT.SVC.CLUSTER.LOCAL:8080/v1",
    ],
)
def test_each_shared_service_is_allow_listed(service, template):
    assert is_service_url(template.format(s=service, S=service.upper()))


@pytest.mark.parametrize("url", NOT_OURS)
def test_no_other_host_is(url):
    assert not is_service_url(url)


def test_the_allow_list_is_the_seven_services_in_their_namespace():
    assert len(SERVICE_HOSTS) == 21
    assert all(host.split(".")[1] == "thalovant" for host in SERVICE_HOSTS)
    assert {host.split(".")[0] for host in SERVICE_HOSTS} == set(SERVICES)


# --- request_headers ----------------------------------------------------------------


def test_request_headers_carry_the_token_for_a_service_url(token):
    headers = request_headers("thalovant-skill-weather", "1.0", "weather/1.0", url=WEATHER)
    assert headers["Authorization"] == f"Bearer {TOKEN_A}"
    assert headers["X-Thalovant-Skill"] == "thalovant-skill-weather"


@pytest.mark.parametrize("url", NOT_OURS)
def test_request_headers_never_carry_it_elsewhere(token, url):
    assert _authorization(request_headers("s", "1", "u", url=url)) == []


def test_request_headers_without_a_url_carry_no_credential(token):
    """What every skill gets today: unchanged until it passes the URL."""
    assert _authorization(request_headers("s", "1", "u")) == []


def test_no_token_file_means_no_header_and_no_error(no_token, caplog):
    with caplog.at_level(logging.DEBUG):
        headers = request_headers("s", "1", "u", url=WEATHER)
    assert _authorization(headers) == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_no_variable_means_no_header(monkeypatch):
    monkeypatch.setattr(service_auth, "_TOKEN", service_auth.ServiceToken())
    monkeypatch.delenv("THALOVANT_SERVICE_TOKEN_FILE", raising=False)
    assert service_token() is None
    assert _authorization(request_headers("s", "1", "u", url=WEATHER)) == []


@pytest.mark.parametrize(
    "content",
    ["", "\n", "not a token", f"{TOKEN_A}\n{TOKEN_B}", f"Bearer {TOKEN_A}", "a.b", "x" * 20000],
)
def test_a_file_that_holds_no_token_sends_none(token, caplog, content):
    token(content)
    with caplog.at_level(logging.WARNING):
        assert _authorization(request_headers("s", "1", "u", url=WEATHER)) == []
        request_headers("s", "1", "u", url=WEATHER)
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) <= 1  # once per file content, and never the content itself
    assert "not a token" not in caplog.text and TOKEN_A not in caplog.text


def test_a_rewritten_file_is_read_again_without_waiting_for_a_401(token):
    assert service_token() == TOKEN_A
    token(TOKEN_B)
    assert service_token() == TOKEN_B
    assert request_headers("s", "1", "u", url=WEATHER)["Authorization"] == f"Bearer {TOKEN_B}"


def test_the_kubelets_symlink_swap_is_seen(tmp_path, monkeypatch):
    """The mounted Secret: token -> ..data/token, ..data -> a timestamped directory."""
    monkeypatch.setattr(service_auth, "_TOKEN", service_auth.ServiceToken())
    mount = tmp_path / "service-token"
    mount.mkdir()

    def publish(name: str, value: str) -> None:
        version = mount / name
        version.mkdir()
        (version / "token").write_text(value)
        staged = mount / "..data_tmp"
        staged.symlink_to(name)
        os.replace(staged, mount / "..data")

    publish("..2026_11_07_10_00_00.1", TOKEN_A)
    (mount / "token").symlink_to("..data/token")
    monkeypatch.setenv("THALOVANT_SERVICE_TOKEN_FILE", str(mount / "token"))
    assert service_token() == TOKEN_A
    publish("..2026_11_07_22_00_00.2", TOKEN_B)
    assert service_token() == TOKEN_B


# --- headers built for a service and sent elsewhere ---------------------------------


@pytest.mark.parametrize("url", NOT_OURS)
def test_a_header_built_for_a_service_loses_the_token_on_the_way_elsewhere(token, url):
    built = request_headers("s", "1", "u", url=WEATHER)
    assert _authorization(with_service_token(url, built)) == []


def test_an_old_token_in_kept_headers_is_dropped_too(token):
    kept = request_headers("s", "1", "u", url=WEATHER)
    token(TOKEN_B)
    request_headers("s", "1", "u", url=WEATHER)
    assert _authorization(with_service_token(EXTERNAL, kept)) == []
    assert with_service_token(WEATHER, kept)["Authorization"] == f"Bearer {TOKEN_B}"


def test_a_callers_own_credential_is_left_alone(token):
    """The memory skill sends its own bearer to the API; that is not the kit's to touch."""
    own = {"Authorization": "Bearer the-skills-own-api-token"}
    assert with_service_token(EXTERNAL, own) == own
    assert with_service_token(WEATHER, own) == own
    lower = {"authorization": "Basic dXNlcjpwdw=="}
    assert with_service_token(WEATHER, lower) == lower


def test_with_service_token_never_changes_the_callers_dict(token):
    headers = {"X-Thalovant-Skill": "s"}
    with_service_token(WEATHER, headers)
    assert headers == {"X-Thalovant-Skill": "s"}


# --- post_json ----------------------------------------------------------------------


class _Response:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload = status, payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


class _Client:
    def __init__(self, *responses, on_call=None):
        self.responses, self.calls, self.on_call = list(responses), [], on_call

    def post(self, url, json=None, timeout=None, headers=None):
        self.calls.append((url, dict(headers or {})))
        if self.on_call:
            self.on_call(len(self.calls))
        return self.responses.pop(0)


def test_post_json_sends_the_token_to_a_service(token):
    client = _Client(_Response(payload={"ok": True}))
    assert post_json(WEATHER, {}, client=client) == {"ok": True}
    assert _authorization(client.calls[0][1]) == [f"Bearer {TOKEN_A}"]


@pytest.mark.parametrize("url", NOT_OURS[:12])
def test_post_json_never_sends_it_elsewhere(token, url):
    client = _Client(_Response())
    post_json(url, {}, headers=request_headers("s", "1", "u", url=WEATHER), client=client)
    assert _authorization(client.calls[0][1]) == []


def test_post_json_without_a_token_sends_what_it_always_sent(no_token):
    client = _Client(_Response(payload={"ok": True}))
    headers = request_headers("s", "1", "u")
    assert post_json(WEATHER, {}, headers=headers, client=client) == {"ok": True}
    assert client.calls[0][1] == headers


def test_a_401_with_the_same_token_is_not_asked_again(token):
    client = _Client(_Response(401))
    assert post_json(WEATHER, {}, client=client, attempts=3) is None
    assert len(client.calls) == 1


def test_a_401_after_the_token_was_re_minted_is_asked_once_more(token):
    # The file changes after the request left; the cache has not seen it yet.
    client = _Client(_Response(401), _Response(payload={"ok": True}),
                     on_call=lambda n: token(TOKEN_B) if n == 1 else None)
    assert post_json(WEATHER, {}, client=client) == {"ok": True}
    assert [_authorization(h) for _, h in client.calls] == [
        [f"Bearer {TOKEN_A}"], [f"Bearer {TOKEN_B}"]]


def test_a_second_401_ends_it(token):
    client = _Client(_Response(401), _Response(401), _Response(payload={"late": 1}),
                     on_call=lambda n: token(TOKEN_B) if n == 1 else None)
    assert post_json(WEATHER, {}, client=client, attempts=3) is None
    assert len(client.calls) == 2


def test_a_401_from_another_host_never_reads_the_token(token, monkeypatch):
    reads = []
    monkeypatch.setattr(service_auth._TOKEN, "reload", lambda: reads.append(1))
    client = _Client(_Response(401))
    assert post_json(EXTERNAL, {}, client=client) is None
    assert reads == [] and len(client.calls) == 1


def test_a_401_without_a_token_picks_up_one_that_arrived(no_token, tmp_path, monkeypatch):
    path = tmp_path / "late-token"
    monkeypatch.setenv("THALOVANT_SERVICE_TOKEN_FILE", str(path))
    client = _Client(_Response(401), _Response(payload={"ok": True}),
                     on_call=lambda n: path.write_text(TOKEN_A) if n == 1 else None)
    assert post_json(WEATHER, {}, client=client) == {"ok": True}
    assert [_authorization(h) for _, h in client.calls] == [[], [f"Bearer {TOKEN_A}"]]


def test_the_token_is_never_logged(token, caplog):
    with caplog.at_level(logging.DEBUG):
        client = _Client(_Response(401), _Response(401),
                         on_call=lambda n: token(TOKEN_B) if n == 1 else None)
        post_json(WEATHER, {}, client=client)
        post_json(EXTERNAL, {}, client=_Client(_Response(500), _Response(500)))
    assert TOKEN_A not in caplog.text and TOKEN_B not in caplog.text


# --- redirects through requests -----------------------------------------------------


class _Adapter(requests.adapters.BaseAdapter):
    """Answers from a table and records every request it is asked to send."""

    def __init__(self, routes):
        super().__init__()
        self.routes, self.seen = routes, []

    def send(self, request, **_kwargs):
        self.seen.append((request.url, dict(request.headers)))
        status, location, body = self.routes[request.url]
        response = requests.Response()
        response.status_code, response.url, response.request = status, request.url, request
        response._content, response._content_consumed = body, True
        response.headers["Content-Type"] = "application/json"
        if location:
            response.headers["Location"] = location
        return response

    def close(self):
        return None


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_service_redirecting_elsewhere_does_not_take_the_token_along(token, status):
    adapter = _Adapter({WEATHER: (status, "http://example.com/collect", b""),
                        "http://example.com/collect": (200, None, b"{}")})
    session = requests.Session()
    session.mount("http://", adapter)
    post_json(WEATHER, {}, client=session)
    assert [url for url, _ in adapter.seen] == [WEATHER, "http://example.com/collect"]
    assert _authorization(adapter.seen[0][1]) == [f"Bearer {TOKEN_A}"]
    assert _authorization(adapter.seen[1][1]) == []


@pytest.mark.parametrize("status", [302, 307])
def test_ask_service_redirected_elsewhere_does_not_take_the_token_along(token, monkeypatch,
                                                                        status):
    answer = f"{KNOWLEDGE}/v1/knowledge/answer"
    adapter = _Adapter({answer: (status, "http://example.com/steal", b""),
                        "http://example.com/steal": (200, None, b'{"text": "x"}')})
    monkeypatch.setattr(requests.Session, "get_adapter", lambda self, url: adapter)
    knowledge.ask_service(service_url=KNOWLEDGE, request_payload={"prompt": "q"},
                          headers=request_headers("s", "1", "u"), timeout=1)
    assert _authorization(adapter.seen[0][1]) == [f"Bearer {TOKEN_A}"]
    assert _authorization(adapter.seen[1][1]) == []


# --- ask_service --------------------------------------------------------------------


class _Posts:
    def __init__(self, *responses, on_call=None):
        self.responses, self.calls, self.on_call = list(responses), [], on_call

    def __call__(self, url, **kwargs):
        self.calls.append((url, dict(kwargs.get("headers") or {})))
        if self.on_call:
            self.on_call(len(self.calls))
        return self.responses.pop(0)


def test_ask_service_adds_the_token_to_the_callers_headers(token, monkeypatch):
    """The knowledge skills pass their own headers, built without a URL."""
    posts = _Posts(_Response(payload={"text": "an answer"}))
    monkeypatch.setattr(knowledge.requests, "post", posts)
    caller = request_headers("thalovant-skill-safety-guide", "1", "u")
    reply = knowledge.knowledge_reply(
        service_url=KNOWLEDGE, prompt="q", lang="en-US", mode="fact", max_sources=1,
        augmentation="auto", age_policy_setting=None, headers=caller, timeout=1)
    assert reply.answer == "an answer"
    assert _authorization(posts.calls[0][1]) == [f"Bearer {TOKEN_A}"]
    assert _authorization(caller) == []  # the caller's dict is not changed


@pytest.mark.parametrize("service_url", [NOT_OURS[1], NOT_OURS[4], NOT_OURS[9]])
def test_ask_service_to_an_owner_set_url_sends_no_token(token, monkeypatch, service_url):
    posts = _Posts(_Response(payload={"text": "x"}))
    monkeypatch.setattr(knowledge.requests, "post", posts)
    knowledge.ask_service(service_url=service_url, request_payload={},
                          headers=request_headers("s", "1", "u", url=KNOWLEDGE), timeout=1)
    assert _authorization(posts.calls[0][1]) == []


def test_ask_service_asks_once_more_after_a_401_with_a_new_token(token, monkeypatch):
    posts = _Posts(_Response(401), _Response(payload={"text": "x"}),
                   on_call=lambda n: token(TOKEN_B) if n == 1 else None)
    monkeypatch.setattr(knowledge.requests, "post", posts)
    assert knowledge.ask_service(service_url=KNOWLEDGE, request_payload={}, headers={},
                                 timeout=1) == {"text": "x"}
    assert [_authorization(h) for _, h in posts.calls] == [
        [f"Bearer {TOKEN_A}"], [f"Bearer {TOKEN_B}"]]


def test_ask_service_reports_a_401_it_cannot_fix(token, monkeypatch):
    posts = _Posts(_Response(401))
    monkeypatch.setattr(knowledge.requests, "post", posts)
    with pytest.raises(requests.HTTPError):
        knowledge.ask_service(service_url=KNOWLEDGE, request_payload={}, headers={}, timeout=1)
    assert len(posts.calls) == 1


class _Streamed(_Response):
    headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def close(self):
        return None


def test_the_streamed_lookup_carries_the_token_and_retries_a_401(token, monkeypatch):
    posts = _Posts(_Streamed(401), _Streamed(payload={"text": "streamed"}),
                   on_call=lambda n: token(TOKEN_B) if n == 1 else None)
    monkeypatch.setattr(knowledge.requests, "post", posts)
    with knowledge.lookup_notice(lambda _line: None):
        answer = knowledge.ask_service(service_url=KNOWLEDGE, request_payload={},
                                       headers={}, timeout=1)
    assert answer == {"text": "streamed"}
    assert [_authorization(h) for _, h in posts.calls] == [
        [f"Bearer {TOKEN_A}"], [f"Bearer {TOKEN_B}"]]


# --- JsonServiceClient (urllib) -----------------------------------------------------


class _Handler(urllib.request.HTTPHandler):
    """urllib's own redirect and error handling over a table of answers."""

    def __init__(self, routes, on_call=None):
        super().__init__()
        self.routes, self.seen, self.on_call = routes, [], on_call

    def http_open(self, req):
        self.seen.append((req.full_url, dict(req.header_items())))
        if self.on_call:
            self.on_call(len(self.seen))
        status, location, body = self.routes[req.full_url]
        if isinstance(status, list):
            status = status.pop(0)
        headers = email.message.Message()
        headers["Content-Type"] = "application/json"
        if location:
            headers["Location"] = location
        response = urllib.response.addinfourl(io.BytesIO(body), headers, req.full_url, status)
        response.msg = "test"
        return response


def _opener(handler):
    return urllib.request.build_opener(handler).open


def test_json_client_sends_the_token_to_a_service(token):
    handler = _Handler({WEATHER: (200, None, b'{"ok": true}')})
    client = JsonServiceClient("s", "1")
    assert client.post(WEATHER, {}, opener=_opener(handler)) == {"ok": True}
    assert _authorization(handler.seen[0][1]) == [f"Bearer {TOKEN_A}"]


@pytest.mark.parametrize("url", ["http://example.com/v1", "http://thalovant-llm:8080/v1",
                                 "http://thalovant-kube-inspector.thalovant.svc.cluster.local/"])
def test_json_client_never_sends_it_elsewhere(token, url):
    handler = _Handler({url: (200, None, b"{}")})
    assert JsonServiceClient("s", "1").post(url, {}, opener=_opener(handler)) == {}
    assert _authorization(handler.seen[0][1]) == []


@pytest.mark.parametrize("status", [301, 302, 303])
def test_json_client_redirected_elsewhere_does_not_take_the_token_along(token, status):
    """urllib copies ordinary headers onto a redirect wherever it points."""
    handler = _Handler({WEATHER: (status, "http://example.com/collect", b""),
                        "http://example.com/collect": (200, None, b"{}")})
    JsonServiceClient("s", "1").post(WEATHER, {}, opener=_opener(handler))
    assert [url for url, _ in handler.seen] == [WEATHER, "http://example.com/collect"]
    assert _authorization(handler.seen[0][1]) == [f"Bearer {TOKEN_A}"]
    assert _authorization(handler.seen[1][1]) == []


def test_json_client_asks_once_more_after_a_401_with_a_new_token(token):
    handler = _Handler({WEATHER: ([401, 200], None, b'{"ok": true}')},
                       on_call=lambda n: token(TOKEN_B) if n == 1 else None)
    client = JsonServiceClient("s", "1")
    assert client.post(WEATHER, {}, opener=_opener(handler)) == {"ok": True}
    assert [_authorization(h) for _, h in handler.seen] == [
        [f"Bearer {TOKEN_A}"], [f"Bearer {TOKEN_B}"]]


def test_json_client_does_not_repeat_a_401_it_cannot_fix(token):
    handler = _Handler({WEATHER: ([401, 200], None, b"{}")})
    client = JsonServiceClient("s", "1")
    assert client.post(WEATHER, {}, opener=_opener(handler)) is None
    assert len(handler.seen) == 1
    # ...and the refusal cools the URL down like any failure.
    assert client.post(WEATHER, {}, opener=_opener(handler)) is None
    assert len(handler.seen) == 1


def test_json_client_without_a_token_is_unchanged(no_token):
    handler = _Handler({WEATHER: (200, None, b"{}")})
    assert JsonServiceClient("s", "1").post(WEATHER, {}, opener=_opener(handler)) == {}
    assert _authorization(handler.seen[0][1]) == []
