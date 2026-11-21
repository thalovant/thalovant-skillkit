"""`RecordStore` on thalovant-api's records store (`ApiBackend`).

A tenant's runtime has no Redis login: the platform renders
`THALOVANT_RECORDS_API_URL`, and the store keeps its records through the API with
the runtime's token from its netrc. What is pinned here: when the API is chosen
(only when nothing else is configured), that the token goes nowhere but the
Authorization header and never into a log, that a slow, absent or refusing API
costs a turn little and leaves the skill on its settings (None), that a refused
change is the change's alone, and that big saves are sent in parts.
"""

from __future__ import annotations

import logging

import pytest
from records_api_fake import TOKEN, URL, FakeRecordsApi, Response, records_sent

from thalovant_skillkit import records
from thalovant_skillkit.records import (
    API_BATCH,
    API_REFUSED_SECONDS,
    API_RETRY_SECONDS,
    API_TIMEOUT,
    UNOWNED,
    ApiBackend,
    PostgresBackend,
    RecordStore,
    RecordStoreError,
    RedisBackend,
    api_url_problem,
    owner_key,
)

SKILL = "thalovant-studio-1a2b3c4d-plant-care"
HOST = "thalovant-api.thalovant.svc.cluster.local"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """A tenant runtime: the URL the platform renders and the netrc it mounts."""
    netrc_file = tmp_path / "netrc"
    netrc_file.write_text(
        f"machine github.com login x password ghp_other\n"
        f"machine {HOST} login runtime password {TOKEN}\n"
    )
    netrc_file.chmod(0o644)  # as the kubelet mounts it: the default-file check would refuse it
    monkeypatch.setenv("NETRC", str(netrc_file))
    monkeypatch.setenv(records.API_URL_ENV, URL)
    for name in ("THALOVANT_RECORDS_REDIS_URL", "REDIS_URL", "DATABASE_URL",
                 "THALOVANT_STUDIO_REDIS_URL", "THALOVANT_STUDIO_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    return netrc_file


def studio_store(api: FakeRecordsApi | None = None, *, clock=None) -> RecordStore:
    store = RecordStore("studio", {}, env_prefix="THALOVANT_STUDIO", default_key=SKILL)
    if api is not None:
        [backend] = store._backend_list()
        assert isinstance(backend, ApiBackend)
        backend._session = api.session()
        if clock is not None:
            backend._clock = clock
    return store


# -- which store -------------------------------------------------------------------------------


def test_the_api_is_used_when_the_platform_names_it_and_nothing_else_is_set(runtime):
    api = FakeRecordsApi()
    store = studio_store(api)

    assert store.enabled
    colour = {"id": "colour", "owner": "client-1", "value": "teal"}
    assert store.save_changes([], [colour]).puts == 1
    assert store.load_owner("client-1") == [{"id": "colour", "owner": "client-1", "value": "teal"}]
    [_, read] = api.requests
    assert read["url"] == f"{URL}/studio/{SKILL}"
    assert read["params"] == {"owner": owner_key("client-1")}


def test_enabled_is_known_before_any_request(runtime):
    api = FakeRecordsApi()
    store = RecordStore("studio", {}, env_prefix="THALOVANT_STUDIO", default_key=SKILL)

    assert store.enabled
    assert api.requests == []


def test_redis_or_postgresql_win_over_the_api(runtime, monkeypatch):
    monkeypatch.setenv("THALOVANT_RECORDS_REDIS_URL", "redis://redis.example:6379/0")
    redis_store = studio_store()
    assert [type(b) for b in redis_store._backend_list()] == [RedisBackend]

    monkeypatch.delenv("THALOVANT_RECORDS_REDIS_URL")
    pg_store = RecordStore("studio", {"database_url": "postgresql://db/x"},
                           env_prefix="THALOVANT_STUDIO", default_key=SKILL)
    assert [type(b) for b in pg_store._backend_list()] == [PostgresBackend]


def test_without_a_token_for_the_api_host_the_skill_keeps_its_settings(runtime, caplog):
    runtime.write_text("machine github.com login x password ghp_other\n")

    with caplog.at_level(logging.WARNING):
        store = studio_store()
        assert not store.enabled
        assert store.load_all() is None and store.load_owner("client-1") is None

    assert "holds no token" in caplog.text and "ghp_other" not in caplog.text


def test_without_a_netrc_the_skill_keeps_its_settings(runtime, tmp_path, monkeypatch):
    monkeypatch.setenv("NETRC", str(tmp_path / "missing"))

    assert not studio_store().enabled


@pytest.mark.parametrize(
    "url",
    [
        "ftp://thalovant-api/v1/runtime/records",
        "http:///v1/runtime/records",
        f"http://runtime:{TOKEN}@{HOST}/v1/runtime/records",
        f"http://{HOST}/v1/runtime/records?x=1",
        "not a url",
    ],
)
def test_an_unusable_url_is_not_used(runtime, monkeypatch, caplog, url):
    monkeypatch.setenv(records.API_URL_ENV, url)

    assert api_url_problem(url) is not None
    with caplog.at_level(logging.WARNING):
        assert not studio_store().enabled
    assert TOKEN not in caplog.text


# -- the token ---------------------------------------------------------------------------------


def test_the_token_is_a_bearer_header_and_nowhere_else(runtime, caplog):
    api = FakeRecordsApi()
    store = studio_store(api)

    with caplog.at_level(logging.DEBUG):
        store.save_changes([], [{"id": "a", "value": 1}])
        store.load_all()
        store.load_owner(None)

    for request in api.requests:
        assert request["headers"]["Authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in request["url"]
        assert TOKEN not in repr(request["params"]) + repr(request["json"])
        assert request["allow_redirects"] is False
        assert request["timeout"] == API_TIMEOUT
    assert TOKEN not in caplog.text
    assert TOKEN not in repr(store._backend_list()[0])


def test_a_record_value_never_reaches_a_log(runtime, caplog):
    api = FakeRecordsApi()
    api.answer = Response(409, {"code": "records_quota_exceeded", "detail": "full"})
    store = studio_store(api)

    with caplog.at_level(logging.DEBUG), pytest.raises(RecordStoreError):
        store.save_changes([], [{"id": "door-code", "value": "4321"}])

    assert "4321" not in caplog.text and TOKEN not in caplog.text
    assert "records_quota_exceeded" in caplog.text


# -- what the API decides ----------------------------------------------------------------------


def test_an_owner_the_runtime_does_not_serve_has_nothing(runtime):
    api = FakeRecordsApi(served={owner_key("client-1")})
    store = studio_store(api)

    store.save_changes([], [{"id": "a", "owner": "client-2", "value": 1},
                            {"id": "b", "owner": "client-1", "value": 2},
                            {"id": "c", "value": 3}])

    assert store.load_owner("client-2") == []
    assert sorted(r["id"] for r in store.load_all()) == ["b", "c"]
    assert store.load_owner(None) == [{"id": "c", "value": 3}]
    assert api.requests[-1]["params"] == {"owner": UNOWNED}


def test_a_refused_change_raises_and_the_next_one_is_sent(runtime):
    api = FakeRecordsApi()
    store = studio_store(api)
    api.answer = Response(413, {"code": "record_too_large"})

    with pytest.raises(RecordStoreError) as raised:
        store.save_changes([], [{"id": "a", "value": "x"}])
    assert not raised.value.acl

    api.answer = None
    assert store.save_changes([], [{"id": "a", "value": "x"}]).puts == 1


# -- when the API is slow, down or refuses -----------------------------------------------------


def test_an_api_that_does_not_answer_leaves_the_skill_on_its_settings_and_is_not_waited_on_again(
    runtime, caplog
):
    api = FakeRecordsApi()
    clock = Clock()
    store = studio_store(api, clock=clock)
    api.fail = ConnectionError(f"could not reach {HOST} with {TOKEN}")

    with caplog.at_level(logging.WARNING):
        assert store.load_owner("client-1") is None
    assert len(api.requests) == 1
    assert TOKEN not in caplog.text
    # Within the pause, no request at all: a turn does not wait on a dead API twice.
    assert store.load_owner("client-1") is None and store.load_all() is None
    with pytest.raises(RecordStoreError):
        store.save_changes([], [{"id": "a"}])
    assert len(api.requests) == 1
    # After it, the API is asked again.
    api.fail = None
    clock.now += API_RETRY_SECONDS + 1
    assert store.load_owner("client-1") == []
    assert len(api.requests) == 2


def test_a_5xx_and_a_page_that_is_not_json_are_failures(runtime):
    api = FakeRecordsApi()
    clock = Clock()
    store = studio_store(api, clock=clock)
    api.answer = Response(502, text="<html>bad gateway</html>")
    assert store.load_all() is None
    clock.now += API_RETRY_SECONDS + 1
    api.answer = Response(200, text="<html>a proxy</html>")
    assert store.load_all() is None


def test_a_refusal_is_said_once_and_asked_again_only_after_a_long_pause(runtime, caplog):
    api = FakeRecordsApi()
    clock = Clock()
    store = studio_store(api, clock=clock)
    api.answer = Response(403, {"code": "skill_not_installed", "detail": "no"})

    with caplog.at_level(logging.WARNING):
        assert store.load_owner("client-1") is None
        clock.now += API_RETRY_SECONDS + 1
        assert store.load_owner("client-1") is None
        with pytest.raises(RecordStoreError) as raised:
            store.save_changes([], [{"id": "a"}])

    assert raised.value.acl  # a refusal: the caller need not log it again
    assert len(api.requests) == 1
    assert caplog.text.count("skill_not_installed") == 1
    clock.now += API_REFUSED_SECONDS
    api.answer = None
    assert store.load_owner("client-1") == []


def test_a_rate_limit_waits_for_its_retry_after(runtime):
    api = FakeRecordsApi()
    clock = Clock()
    store = studio_store(api, clock=clock)
    api.answer = Response(429, {"code": "runtime_records_rate_limited"}, {"Retry-After": "7"})

    assert store.load_all() is None
    api.answer = None
    clock.now += 6
    assert store.load_all() is None and len(api.requests) == 1
    clock.now += 2
    assert store.load_all() == []


def test_a_redirect_is_not_followed(runtime):
    api = FakeRecordsApi()
    api.answer = Response(302, None, {"Location": "https://elsewhere.example/"})
    store = studio_store(api)

    assert store.load_all() is None
    assert api.requests[0]["allow_redirects"] is False


def test_malformed_rows_are_skipped(runtime):
    api = FakeRecordsApi()
    api.answer = Response(200, {"records": [
        {"owner": UNOWNED, "id": "ok", "body": '{"id": "ok"}'},
        {"owner": UNOWNED, "id": 3, "body": "{}"},
        "junk",
        {"owner": UNOWNED, "id": "list", "body": "[1, 2]"},
        {"owner": UNOWNED, "id": "text", "body": "not json"},
    ]})

    assert studio_store(api).load_all() == [{"id": "ok"}]


# -- big saves ---------------------------------------------------------------------------------


def test_a_big_save_goes_in_parts(runtime):
    api = FakeRecordsApi()
    store = studio_store(api)
    before = [{"id": str(i), "owner": "client-1", "n": i} for i in range(API_BATCH * 2 + 50)]

    assert store.save_changes([], before).puts == len(before)
    posts = [r for r in api.requests if r["method"] == "POST"]
    assert [len(p["json"]["puts"]) for p in posts] == [API_BATCH, API_BATCH, 50]

    after = before[:10]
    assert store.save_changes(before, after).deletes == len(before) - 10
    posts = [r for r in api.requests if r["method"] == "POST"][3:]
    assert all(len(p["json"]["puts"]) + len(p["json"]["deletes"]) <= API_BATCH for p in posts)
    assert len(store.load_all()) == 10


def test_a_save_of_big_records_is_split_by_bytes(runtime):
    api = FakeRecordsApi()
    store = studio_store(api)
    big = [{"id": str(i), "blob": "x" * 60_000} for i in range(20)]

    store.save_changes([], big)

    posts = [r for r in api.requests if r["method"] == "POST"]
    assert len(posts) > 1
    for post in posts:
        assert sum(len(p["body"].encode()) for p in post["json"]["puts"]) <= records.API_BATCH_BYTES
    assert "x" * 60_000 in records_sent(api)
