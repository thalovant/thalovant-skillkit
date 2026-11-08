import json
import logging
import sys
import types

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


# ---- a PostgreSQL that fails, and comes back ------------------------------------------------


class FakeConnection:
    """What `JsonStateStore` asks of a psycopg connection, holding one document."""

    def __init__(self, driver):
        self.driver = driver
        self.autocommit = False
        self.broken = False
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        if self.conn.broken:
            raise OSError("the connection is closed")
        if sql.startswith("select"):
            document = self.conn.driver.document
            self.row = None if document is None else (document,)
        elif sql.startswith("insert"):
            self.conn.driver.document = json.loads(params[2])

    def fetchone(self):
        return self.row


class FakeDriver(types.ModuleType):
    """A `psycopg` module whose server can be down."""

    def __init__(self, document=None):
        super().__init__("psycopg")
        self.document = document
        self.down = False
        self.made: list[FakeConnection] = []

    def connect(self, url, connect_timeout=None):
        if self.down:
            raise OSError("connection refused")
        conn = FakeConnection(self)
        self.made.append(conn)
        return conn


def postgres_only(monkeypatch, document=None):
    for name in ("REDIS_URL", "REDIS_SENTINEL_URLS", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"THALOVANT_TIMER_{name}", raising=False)
    driver = FakeDriver(document)
    monkeypatch.setitem(sys.modules, "psycopg", driver)
    return make_store({"database_url": "postgresql://example"}), driver


def test_a_postgres_that_could_not_be_reached_is_tried_again_after_a_while(monkeypatch, caplog):
    """A failed connect used to turn PostgreSQL off for the life of the process."""
    store, driver = postgres_only(monkeypatch, [{"id": "kept"}])
    driver.down = True
    with caplog.at_level(logging.WARNING):
        assert store.load() is None
        assert store.load() is None
    assert caplog.text.count("Postgres unreachable (OSError)") == 1, "not asked again at once"
    driver.down = False
    assert store.load() is None and not driver.made, "still within the pause"
    store._pg_retry_at = 0.0  # as if a minute had passed
    assert store.load() == [{"id": "kept"}]
    assert store.database_url, "PostgreSQL is not turned off"


def test_a_connection_postgres_closed_is_replaced_on_the_next_call(monkeypatch):
    """A PostgreSQL restart closes the connection under the store; it used to keep the dead one,
    so every load and save after it failed until the process restarted."""
    store, driver = postgres_only(monkeypatch, [{"id": "kept"}])
    assert store.load() == [{"id": "kept"}]
    driver.made[0].broken = True
    assert store.load() is None
    assert driver.made[0].closed, "the dead connection is closed and forgotten"
    assert store.load() == [{"id": "kept"}] and len(driver.made) == 2
    driver.made[1].broken = True
    store.save([{"id": "lost"}])  # fails, logged
    store.save([{"id": "new"}])
    assert driver.document == [{"id": "new"}] and len(driver.made) == 3


def test_without_the_driver_postgres_is_off_for_good(monkeypatch, caplog):
    store, _ = postgres_only(monkeypatch)
    monkeypatch.setitem(sys.modules, "psycopg", None)  # `import psycopg` raises ImportError
    with caplog.at_level(logging.WARNING):
        assert store.load() is None and store.load() is None
    assert store.database_url == ""
    assert caplog.text.count("Postgres disabled") == 1


def test_load_without_redis_reads_postgres_only(monkeypatch):
    """For a caller Redis has refused the key: PostgreSQL's copy, and nothing written back."""
    store = make_store({"redis_url": "redis://example", "database_url": "postgresql://example"})

    def never(*args):
        raise AssertionError("Redis is not asked")

    monkeypatch.setattr(store, "_load_redis", never)
    monkeypatch.setattr(store, "_save_redis", never)
    monkeypatch.setattr(store, "_load_postgres", lambda: [{"id": "kept"}])
    assert store.load(redis=False) == [{"id": "kept"}]
