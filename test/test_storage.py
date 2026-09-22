import json

from thalovant_skillkit.storage import JsonStateStore


def make_store(settings=None):
    return JsonStateStore("speaker", settings or {}, env_prefix="THALOVANT_TIMER",
                          default_key="timers")


def test_existing_configuration_precedence_and_key_are_preserved(monkeypatch):
    monkeypatch.setenv("THALOVANT_TIMER_STATE_KEY", "custom")
    monkeypatch.setenv("THALOVANT_TIMER_REDIS_URL", "redis://specific")
    monkeypatch.setenv("REDIS_URL", "redis://shared")
    store = make_store()
    assert store._store_key() == "thalovant:speaker:custom"
    assert store.redis_url == "redis://specific"
    assert make_store({"redis_url": "redis://setting"}).redis_url == "redis://setting"


def test_unconfigured_store_keeps_local_fallback(monkeypatch):
    for name in ("REDIS_URL", "REDIS_SENTINEL_URLS", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"THALOVANT_TIMER_{name}", raising=False)
    store = make_store()
    assert not store.enabled
    assert store.load() is None
    assert store.save([{"id": "local"}]) is None


def test_redis_miss_falls_back_and_repopulates_cache(monkeypatch):
    store = make_store({"redis_url": "redis://example"})
    records = [{"id": "existing", "remaining": 15}]
    saved = []
    monkeypatch.setattr(store, "_load_redis", lambda: None)
    monkeypatch.setattr(store, "_load_postgres", lambda: records)
    monkeypatch.setattr(store, "_save_redis", saved.append)
    assert store.load() == records
    assert saved == [records]


def test_save_reaches_postgres_when_cache_is_unavailable(monkeypatch):
    store = make_store({"redis_url": "redis://example"})

    class BrokenCache:
        def set(self, *args):
            raise OSError("unavailable")

    saved = []
    monkeypatch.setattr(store, "_redis_client", lambda: BrokenCache())
    monkeypatch.setattr(store, "_save_postgres", saved.append)
    records = [{"id": "alarm"}]
    store.save(records)
    assert saved == [records]


def test_postgres_uses_existing_table_and_parameterized_scope(monkeypatch):
    store = make_store({"database_url": "postgresql://example"})
    calls = []

    class Connection:
        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, values):
            calls.append((sql, values))

    monkeypatch.setattr(store, "_postgres", lambda: Connection())
    store._save_postgres([{"id": "saved"}])
    sql, values = calls[0]
    assert "thalovant_skill_state" in sql
    assert values[:2] == ("speaker", "timers")
    assert json.loads(values[2]) == [{"id": "saved"}]


def test_backend_error_messages_cannot_leak_credentials(monkeypatch, caplog):
    store = make_store({"redis_url": "redis://example"})

    class BrokenCache:
        def get(self, key):
            raise OSError("password=private-example")

    monkeypatch.setattr(store, "_redis_client", lambda: BrokenCache())
    assert store.load() is None
    assert "OSError" in caplog.text
    assert "private-example" not in caplog.text
