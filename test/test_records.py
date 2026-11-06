"""The per-owner record store: one operation suite on every backend, then two pods at once.

The in-memory backend runs on a dict, Redis on fakeredis (which runs the real
Lua), PostgreSQL through the real SQL over a sqlite3 connection that speaks
psycopg's dialect (`PgOverSqlite`). The `-live` kinds run the same suite on a
real Redis and a real PostgreSQL when `THALOVANT_RECORDS_TEST_REDIS_URL` /
`THALOVANT_RECORDS_TEST_DATABASE_URL` name one (they are emptied first: use
scratch servers); otherwise they are skipped.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager

import pytest

from thalovant_skillkit.records import (
    DEFAULT_KEY_PREFIX,
    MAX_BODY_BYTES,
    REDIS_ACL_COMMANDS,
    UNOWNED,
    Changes,
    MemoryBackend,
    PostgresBackend,
    RecordStore,
    RecordStoreError,
    RedisBackend,
    owner_key,
    valid_key_prefix,
)
from thalovant_skillkit.storage import JsonStateStore
from thalovant_skillkit.testing import FakeRecordStore

fakeredis = pytest.importorskip("fakeredis")

SCOPE, KEY = "alarm", "alarms"


def rec(owner, rid, **more):
    return {"id": rid, "owner": owner, **more}


def by_id(records):
    return sorted(records, key=lambda r: (str(r.get("owner")), str(r.get("id"))))


# ---- the PostgreSQL dialect over sqlite ----------------------------------------------------


class PgCursor:
    def __init__(self, raw: sqlite3.Cursor):
        self._raw = raw

    def execute(self, sql: str, params: tuple = ()):
        sql = sql.replace("%s::jsonb", "%s").replace("%s", "?")
        if "pg_advisory_xact_lock" in sql:
            sql, params = "select 1", ()  # the transaction already holds sqlite's one writer lock
        sql = sql.replace("seq bigserial,", "seq integer not null default 0,")
        sql = sql.replace("body jsonb", "body text").replace(
            "timestamptz not null default now()", "real not null default 0"
        )
        sql = (
            sql.replace("extract(epoch from at)", "at")
            .replace("to_timestamp(?)", "?")
            .replace("now()", "0")
        )
        sql = sql.replace("order by seq", "order by rowid")
        self._raw.execute(sql, params)

    def fetchone(self):
        return self._raw.fetchone()

    def fetchall(self):
        return self._raw.fetchall()


class PgOverSqlite:
    """What `PostgresBackend` asks of a psycopg connection."""

    def __init__(self, path: str):
        self._conn = sqlite3.connect(
            path, isolation_level=None, timeout=60, check_same_thread=False
        )

    def cursor(self) -> PgCursor:
        return PgCursor(self._conn.cursor())

    @contextmanager
    def transaction(self):
        self._conn.execute("begin immediate")
        try:
            yield
        except BaseException:
            self._conn.execute("rollback")
            raise
        self._conn.execute("commit")

    def close(self) -> None:
        self._conn.close()


# ---- the backends, each as "make me another store over the same data" ------------------------


@pytest.fixture(params=["memory", "redis", "postgres", "redis-live", "postgres-live"])
def pods(request, tmp_path):
    """A factory: each call is a new store (a new pod) over one shared backend."""
    kind = request.param
    if kind == "redis-live":
        url = os.environ.get("THALOVANT_RECORDS_TEST_REDIS_URL")
        if not url:
            pytest.skip("no THALOVANT_RECORDS_TEST_REDIS_URL")
        import redis

        redis.Redis.from_url(url).flushdb()
        return lambda scope=SCOPE, key=KEY: make(
            RedisBackend(redis.Redis.from_url(url), scope, key), scope, key
        )
    if kind == "postgres-live":
        url = os.environ.get("THALOVANT_RECORDS_TEST_DATABASE_URL")
        if not url:
            pytest.skip("no THALOVANT_RECORDS_TEST_DATABASE_URL")
        import psycopg

        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("drop table if exists thalovant_records")
            conn.execute("drop table if exists thalovant_records_meta")
        return lambda scope=SCOPE, key=KEY: make(
            PostgresBackend(lambda: psycopg.connect(url, autocommit=True), scope, key), scope, key
        )
    if kind == "memory":
        # A backend is one (scope, key), as a Redis prefix or a pair of columns is.
        shared: dict = {}
        return lambda scope=SCOPE, key=KEY: make(
            shared.setdefault((scope, key), MemoryBackend()), scope, key
        )
    if kind == "redis":
        server = fakeredis.FakeServer()
        return lambda scope=SCOPE, key=KEY: make(
            RedisBackend(fakeredis.FakeStrictRedis(server=server), scope, key), scope, key
        )
    path = str(tmp_path / "pg.sqlite")
    return lambda scope=SCOPE, key=KEY: make(
        PostgresBackend(lambda: PgOverSqlite(path), scope, key), scope, key
    )


def make(backend, scope=SCOPE, key=KEY, **fields):
    store = RecordStore(
        scope, {}, env_prefix="THALOVANT_ALARM", default_key=key, backends=[backend], **fields
    )
    store.backend = backend
    return store


# ---- the operations, the same on every backend ---------------------------------------------


def test_records_round_trip_per_owner(pods):
    store = pods()
    records = [rec("anna", "1", due=10), rec("anna", "2", due=20), rec("ben", "1", due=30)]
    assert store.save_changes([], records) == Changes(puts=3, deletes=0)
    assert by_id(store.load_all()) == by_id(records)
    assert by_id(store.load_owner("anna")) == by_id(records[:2])
    assert store.load_owner("ben") == [records[2]]
    assert store.load_owner("nobody") == []
    keys = store.owners()
    assert sorted(keys) == sorted([owner_key("anna"), owner_key("ben")])
    assert "anna" not in keys and "ben" not in keys, "keys, never labels"


def test_a_save_writes_only_what_changed(pods):
    store = pods()
    before = [rec("anna", str(i), due=i) for i in range(100)]
    store.save_changes([], before)
    after = [dict(r) for r in before]
    after[7]["due"] = 999
    after.append(rec("ben", "new"))
    del after[3]
    assert store.save_changes(before, after) == Changes(puts=2, deletes=1)
    assert store.save_changes(after, after) == Changes(0, 0)
    loaded = {(r["owner"], r["id"]): r for r in store.load_all()}
    assert len(loaded) == 100 and loaded[("anna", "7")]["due"] == 999
    assert ("anna", "3") not in loaded and ("ben", "new") in loaded


def test_an_unchanged_save_does_not_reach_the_backend():
    backend = MemoryBackend()
    store = make(backend)
    records = [rec("anna", "1")]
    store.save_changes([], records)
    calls = backend.calls
    store.save_changes(records, [dict(records[0])])
    assert backend.calls == calls


def test_a_pod_with_a_stale_copy_does_not_overwrite_the_others(pods):
    """The whole-document store lost this: pod B saved its list and erased what pod A added."""
    pod_a, pod_b = pods(), pods()
    start = [rec("anna", "1"), rec("ben", "1")]
    pod_a.save_changes([], start)
    copy_a, copy_b = pod_a.load_all(), pod_b.load_all()
    # Pod A adds an alarm for anna; pod B, with a copy from before, changes ben's.
    pod_a.save_changes(copy_a, copy_a + [rec("anna", "2")])
    changed = [dict(r, due=5) if r["owner"] == "ben" else r for r in copy_b]
    pod_b.save_changes(copy_b, changed)
    final = {(r["owner"], r["id"]): r for r in pods().load_all()}
    assert set(final) == {("anna", "1"), ("anna", "2"), ("ben", "1")}
    assert final[("ben", "1")]["due"] == 5


def test_removing_the_last_record_takes_the_owner_out(pods):
    store = pods()
    mine = [rec("anna", "1")]
    store.save_changes([], mine + [rec("ben", "1")])
    store.save_changes(mine + [rec("ben", "1")], mine)
    assert store.owners() == [owner_key("anna")]
    assert store.load_owner("ben") == []
    store.save_changes(mine, [])
    assert store.load_all() == [] and store.owners() == []


TRICKY = ["a", "a:b", "", "é", "日本語", "x" * 5000, "ａ", "A", " a", "a ", "a/b", "a%3Ab"]


def test_no_two_owners_meet_however_their_labels_look(pods):
    store = pods()
    records = [rec(label, "1", mine=label) for label in TRICKY]
    store.save_changes([], records)
    assert len(store.load_all()) == len(TRICKY)
    assert len(store.owners()) == len(TRICKY)
    for label in TRICKY:
        assert [r["mine"] for r in store.load_owner(label)] == [label]
    store.save_changes(records, [r for r in records if r["owner"] != "a"])
    assert store.load_owner("a") == [] and len(store.load_owner("a:b")) == 1


def test_a_record_with_no_owner_lives_in_its_own_bucket(pods):
    store = pods()
    unowned = {"id": "u1", "text": "no owner field"}
    store.save_changes([], [unowned, rec("", "1"), {"id": "u2", "owner": None}])
    assert unowned in store.load_all()
    assert (
        store.load_owner(None) == [unowned, {"id": "u2", "owner": None}]
        or len(store.load_owner(None)) == 2
    )
    assert store.load_owner("") == [rec("", "1")], (
        "an empty label is an owner, not the unowned bucket"
    )
    assert UNOWNED in store.owners()


def test_a_record_without_an_id_is_keyed_by_its_content(pods):
    store = pods()
    first = {"owner": "anna", "text": "milk"}
    store.save_changes([], [first])
    changed = {"owner": "anna", "text": "oat milk"}
    assert store.save_changes([first], [changed]) == Changes(puts=1, deletes=1)
    assert store.load_all() == [changed]
    assert store.save_changes([changed], [changed]) == Changes()


def test_scopes_and_keys_with_colons_do_not_alias(pods):
    one, other = pods("a", "b:c"), pods("a:b", "c")
    one.save_changes([], [rec("anna", "1", where="one")])
    other.save_changes([], [rec("anna", "1", where="other")])
    assert one.load_all() == [rec("anna", "1", where="one")]
    assert other.load_all() == [rec("anna", "1", where="other")]


def test_replace_owner_reads_one_owner_afresh(pods):
    store, other = pods(), pods()
    store.save_changes([], [rec("anna", "1"), rec("ben", "1")])
    mine = store.load_all()
    other.save_changes([rec("anna", "1")], [rec("anna", "1", due=1), rec("anna", "2")])
    merged = store.replace_owner(mine, "anna")
    assert by_id(merged) == by_id([rec("anna", "1", due=1), rec("anna", "2"), rec("ben", "1")])


def test_the_pattern_a_skill_follows_keeps_two_pods_in_step(pods):
    """The migration guide's loop: a working list, a snapshot, a read of the owner each turn."""
    import copy

    class Skill:
        def __init__(self, store):
            self.store, self.alarms = store, []
            loaded = store.load_all_with_legacy(LegacyDocument(None))
            self.alarms = loaded or []
            self.persisted = copy.deepcopy(self.alarms)

        def turn(self, owner):  # read this owner's records afresh before acting
            mine = self.store.load_owner(owner)
            if mine is not None:
                self.alarms = self.store.splice_owner(self.alarms, owner, mine)
                self.persisted = self.store.splice_owner(self.persisted, owner, mine)

        def save(self):
            try:
                self.store.save_changes(self.persisted, self.alarms)
                self.persisted = copy.deepcopy(self.alarms)
            except RecordStoreError:
                pass  # the change stays in memory; the next save sends it again

        def add(self, owner, rid, **more):
            self.turn(owner)
            self.alarms.append(rec(owner, rid, **more))
            self.save()

    one, two = Skill(pods()), Skill(pods())
    one.add("anna", "1")
    two.add("ben", "1")      # two started before anna's alarm existed
    two.add("anna", "2")     # reads anna afresh first: sees alarm 1, adds 2
    one.add("ben", "2")
    final = {(r["owner"], r["id"]) for r in pods().load_all()}
    assert final == {("anna", "1"), ("anna", "2"), ("ben", "1"), ("ben", "2")}


def test_twenty_threads_over_two_pods_lose_nothing(pods):
    pod_a, pod_b = pods(), pods()
    errors = []

    def work(store, owner):
        try:
            mine: list[dict] = []
            for i in range(15):
                added = mine + [rec(owner, str(i), n=i)]
                store.save_changes(mine, added)
                mine = added
            kept = [r for r in mine if int(r["id"]) % 5]
            store.save_changes(mine, kept)
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [
        threading.Thread(target=work, args=((pod_a if n % 2 else pod_b), f"owner-{n}"))
        for n in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    final = pods().load_all()
    assert len(final) == 20 * 12, "three of every five went, nothing else"
    assert len({(r["owner"], r["id"]) for r in final}) == len(final), "no duplicates"
    assert len(pods().owners()) == 20


def test_a_record_that_is_not_json_is_refused_before_anything_is_written():
    backend = MemoryBackend()
    store = make(backend)
    with pytest.raises(RecordStoreError, match="not JSON"):
        store.save_changes([], [rec("anna", "1"), rec("anna", "2", bad=object())])
    assert backend.calls == 0 and backend.data == {}
    with pytest.raises(RecordStoreError, match="over"):
        store.save_changes([], [rec("anna", "1", text="x" * (MAX_BODY_BYTES + 1))])
    with pytest.raises(RecordStoreError, match="not a dict"):
        store.save_changes([], ["a string"])
    with pytest.raises(RecordStoreError, match="not valid text"):
        store.save_changes([], [rec("\ud800", "1")])


# ---- when a database is down ----------------------------------------------------------------


def test_a_backend_that_is_down_raises_on_save_and_reads_as_none():
    backend = MemoryBackend()
    store = make(backend)
    store.save_changes([], [rec("anna", "1")])
    backend.fail = OSError("down")
    with pytest.raises(RecordStoreError, match="down"):
        store.save_changes([], [rec("anna", "2")])
    assert store.load_all() is None, "the caller keeps its settings"
    assert store.load_owner("anna") is None
    backend.fail = None
    assert store.load_all() == [rec("anna", "1")], "nothing was half written"
    store.save_changes([rec("anna", "1")], [rec("anna", "1"), rec("anna", "2")])
    assert len(store.load_all()) == 2


def test_with_two_backends_one_down_the_other_is_still_written():
    primary, mirror = MemoryBackend(), MemoryBackend()
    store = RecordStore(SCOPE, {}, env_prefix="X", default_key=KEY, backends=[primary, mirror])
    mirror.fail = OSError("down")
    with pytest.raises(RecordStoreError, match="memory: OSError"):
        store.save_changes([], [rec("anna", "1")])
    assert primary.data and not mirror.data
    assert store.load_all() == [rec("anna", "1")], "a read is served by the one that answers"


def test_an_empty_redis_is_refilled_from_postgres(tmp_path):
    server = fakeredis.FakeServer()
    cache = RedisBackend(fakeredis.FakeStrictRedis(server=server), SCOPE, KEY)
    durable = PostgresBackend(lambda: PgOverSqlite(str(tmp_path / "pg.sqlite")), SCOPE, KEY)
    store = RecordStore(SCOPE, {}, env_prefix="X", default_key=KEY, backends=[cache, durable])
    store.save_changes([], [rec("anna", "1"), rec("ben", "1")])
    fresh_cache = RedisBackend(fakeredis.FakeStrictRedis(server=fakeredis.FakeServer()), SCOPE, KEY)
    again = RecordStore(SCOPE, {}, env_prefix="X", default_key=KEY, backends=[fresh_cache, durable])
    assert by_id(again.load_all()) == by_id([rec("anna", "1"), rec("ben", "1")])
    assert len(fresh_cache.load_all()) == 2, "the cache came back"


# ---- the old whole document ---------------------------------------------------------------


class LegacyDocument:
    """What `JsonStateStore` is to the migration: something with `load()`."""

    def __init__(self, document):
        self.document = document
        self.loads = 0
        self.saves = 0

    def load(self):
        self.loads += 1
        return None if self.document is None else [dict(r) for r in self.document]

    def save(self, value):  # the migration must never write the old document
        self.saves += 1


def test_the_legacy_document_is_imported_once_and_left_alone(pods):
    store = pods()
    legacy = LegacyDocument([rec("anna", "1", due=1), rec("anna", "2"), rec("ben", "1")])
    assert store.migrate_legacy(legacy) == 3
    assert by_id(store.load_all()) == by_id(legacy.document)
    assert store.migrate_legacy(legacy) == 0 and store.migrate_legacy(legacy) == 0
    assert legacy.saves == 0 and len(legacy.document) == 3
    # A pod that starts later finds it done and never opens the old document.
    later = pods()
    loads = legacy.loads
    assert later.migrate_legacy(legacy) == 0 and legacy.loads == loads


def test_a_newer_record_is_not_overwritten_by_the_legacy_import(pods):
    store = pods()
    store.save_changes([], [rec("anna", "1", due=99)])
    assert store.migrate_legacy(LegacyDocument([rec("anna", "1", due=1), rec("anna", "2")])) == 1
    assert {r["id"]: r.get("due") for r in store.load_all()} == {"1": 99, "2": None}


def test_two_pods_migrating_together_import_it_once(pods):
    legacy = LegacyDocument([rec(f"o{n}", str(i)) for n in range(5) for i in range(4)])
    totals, errors = [], []

    def run():
        try:
            totals.append(pods().migrate_legacy(legacy))
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert sum(totals) == 20, totals
    assert len(pods().load_all()) == 20


def test_an_empty_legacy_document_is_done_and_no_document_is_tried_again(pods):
    store = pods()
    assert store.migrate_legacy(LegacyDocument([])) == 0
    assert store.migrate_legacy(LegacyDocument([rec("anna", "1")])) == 0, "done is done"
    assert store.load_all() == []
    unreachable = pods("other", "other")
    gone = LegacyDocument(None)
    assert unreachable.migrate_legacy(gone) == 0
    gone.document = [rec("anna", "1")]
    unreachable._legacy_checked = 0.0  # as if five minutes had passed
    assert unreachable.migrate_legacy(gone) == 1, (
        "an unreachable legacy store is not a finished migration"
    )


def test_an_unfinished_claim_is_taken_over_after_its_time():
    backend = MemoryBackend()
    store = make(backend)
    assert backend.migration_claim("pod-that-died", 300)
    assert store.migrate_legacy(LegacyDocument([rec("anna", "1")])) == 0, "someone else is on it"
    assert backend.migration_claim("pod-two", 0)  # its time is up
    backend.meta["migration"] = "running:pod-two:0"  # a claim from long ago
    assert store.migrate_legacy(LegacyDocument([rec("anna", "1")])) == 1
    assert backend.migration_state() == "done"


def test_a_failure_while_importing_leaves_the_migration_to_be_repeated():
    backend = MemoryBackend()
    store = make(backend)
    legacy = LegacyDocument([rec("anna", "1")])
    real = backend.put_if_absent

    def broken(items):
        raise OSError("down")

    backend.put_if_absent = broken
    with pytest.raises(RecordStoreError, match="migrating"):
        store.migrate_legacy(legacy)
    assert backend.migration_state() == "running"
    backend.put_if_absent = real
    backend.meta["migration"] = "running:old:0"
    assert store.migrate_legacy(legacy) == 1 and store.load_all() == [rec("anna", "1")]


def test_load_all_with_legacy_migrates_then_reads(monkeypatch):
    backend = MemoryBackend()
    store = make(backend)
    legacy = LegacyDocument([rec("anna", "1")])
    assert store.load_all_with_legacy(legacy) == [rec("anna", "1")]
    # Without an argument the legacy document is the kit's own: same settings, same key.
    other = make(MemoryBackend(), "alarm2", "alarms2")
    monkeypatch.setattr(other._config, "load", lambda: [rec("ben", "9")])
    assert other.load_all_with_legacy() == [rec("ben", "9")]


# ---- what is set up ----------------------------------------------------------------------------


def test_with_no_database_the_skill_keeps_its_settings(monkeypatch):
    for name in ("REDIS_URL", "REDIS_SENTINEL_URLS", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"THALOVANT_ALARM_{name}", raising=False)
    store = RecordStore(SCOPE, {}, env_prefix="THALOVANT_ALARM", default_key=KEY)
    assert not store.enabled
    assert store.load_all() is None and store.load_owner("anna") is None
    assert store.save_changes([], [rec("anna", "1")]) == Changes()
    assert store.migrate_legacy() == 0 and store.load_all_with_legacy() is None
    assert store.owners() == []


def test_the_same_settings_and_environment_turn_it_on(monkeypatch):
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        JsonStateStore, "_redis_client", lambda self: fakeredis.FakeStrictRedis(server=server)
    )
    monkeypatch.setenv("THALOVANT_ALARM_STATE_KEY", "custom")
    monkeypatch.setenv("THALOVANT_ALARM_REDIS_URL", "redis://example")
    store = RecordStore(SCOPE, {}, env_prefix="THALOVANT_ALARM", default_key=KEY)
    assert store.enabled and store.key == "custom"
    store.save_changes([], [rec("anna", "1")])
    names = [k.decode() for k in fakeredis.FakeStrictRedis(server=server).keys("*")]
    assert f"thalovant:records:v1:alarm:custom:{owner_key('anna')}" in names
    assert "thalovant:records:v1:alarm:custom:owners" in names
    assert not any(n.startswith("thalovant:alarm:") for n in names), (
        "the old document key is not touched"
    )
    assert store.load_all() == [rec("anna", "1")]
    assert RecordStore(
        SCOPE, {"database_url": "postgresql://example"}, env_prefix="X", default_key=KEY
    ).enabled


def test_through_the_settings_on_a_real_redis_and_postgres_together():
    """The way an operator turns it on: both URLs in the settings, Redis read, PostgreSQL kept."""
    redis_url = os.environ.get("THALOVANT_RECORDS_TEST_REDIS_URL")
    database_url = os.environ.get("THALOVANT_RECORDS_TEST_DATABASE_URL")
    if not (redis_url and database_url):
        pytest.skip("no live servers named")
    import psycopg
    import redis

    redis.Redis.from_url(redis_url).flushdb()
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("drop table if exists thalovant_records")
        conn.execute("drop table if exists thalovant_records_meta")
    settings = {"redis_url": redis_url, "database_url": database_url}
    store = RecordStore("live", settings, env_prefix="THALOVANT_LIVE", default_key="things")
    assert store.enabled and store.load_all_with_legacy() == []
    records = [rec("anna", "1", due=1), rec("ben", "1")]
    assert store.save_changes([], records) == Changes(puts=2, deletes=0)
    # The old whole-document key is never written.
    assert not redis.Redis.from_url(redis_url).exists("thalovant:live:things")
    redis.Redis.from_url(redis_url).flushdb()  # Redis lost its data: PostgreSQL still has it
    again = RecordStore("live", settings, env_prefix="THALOVANT_LIVE", default_key="things")
    assert by_id(again.load_all()) == by_id(records)
    assert redis.Redis.from_url(redis_url).scard("thalovant:records:v1:live:things:owners") == 2


def test_a_configured_redis_that_cannot_be_built_leaves_no_backend(monkeypatch):
    monkeypatch.setattr(JsonStateStore, "_redis_client", lambda self: None)
    store = RecordStore(SCOPE, {"redis_url": "redis://example"}, env_prefix="X", default_key=KEY)
    assert store.load_all() is None and store.save_changes([], [rec("anna", "1")]) == Changes()


def test_the_fake_store_behaves_like_the_real_one():
    store = FakeRecordStore("alarm")
    assert store.enabled
    store.save_changes([], [rec("anna", "1"), rec("ben", "1")])
    assert by_id(store.load_all()) == by_id([rec("anna", "1"), rec("ben", "1")])
    assert store.backend.calls > 0
    store.backend.fail = OSError("down")
    with pytest.raises(RecordStoreError):
        store.save_changes([], [rec("anna", "2")])
    assert store.load_all() is None
    # The legacy way in works on the fake too.
    fresh = FakeRecordStore("alarm", owner_field="who", id_field="key")
    assert fresh.migrate_legacy(LegacyDocument([{"key": "k", "who": "anna"}])) == 1
    assert fresh.load_owner("anna") == [{"key": "k", "who": "anna"}]


def test_owner_keys_are_fixed_size_and_stable():
    assert owner_key("anna") == owner_key("anna") and len(owner_key("x" * 10**6)) == 40
    assert len(owner_key("\ud800")) == 40 and owner_key("\ud800") != owner_key("\ud801")
    assert owner_key("a") != owner_key("a:b") and owner_key("") != UNOWNED


# ---- a key prefix, for a Redis user that may only touch some keys -------------------------------


def names(server) -> list[str]:
    return sorted(k.decode() for k in fakeredis.FakeStrictRedis(server=server).keys("*"))


def build_on(server, monkeypatch, settings=None, env_prefix="THALOVANT_ALARM"):
    monkeypatch.setattr(
        JsonStateStore, "_redis_client", lambda self: fakeredis.FakeStrictRedis(server=server)
    )
    base = {"redis_url": "redis://example"}
    return RecordStore(
        SCOPE, {**base, **(settings or {})}, env_prefix=env_prefix, default_key=KEY
    )


def test_without_a_prefix_the_keys_are_what_0_31_0_wrote(monkeypatch):
    for name in ("THALOVANT_ALARM_KEY_PREFIX", "THALOVANT_RECORDS_KEY_PREFIX"):
        monkeypatch.delenv(name, raising=False)
    server = fakeredis.FakeServer()
    store = build_on(server, monkeypatch)
    assert store.key_prefix == DEFAULT_KEY_PREFIX == "thalovant"
    store.save_changes([], [rec("anna", "1")])
    store.migrate_legacy(LegacyDocument([rec("ben", "1")]))
    ok = owner_key("anna")
    assert names(server) == sorted([
        f"thalovant:records:v1:alarm:alarms:{ok}",
        f"thalovant:records:v1:alarm:alarms:{owner_key('ben')}",
        "thalovant:records:v1:alarm:alarms:owners",
        "thalovant:records:v1:alarm:alarms:migration",
    ])


@pytest.mark.parametrize("how", ["setting", "own-env", "shared-env"])
def test_every_redis_key_goes_under_the_prefix(monkeypatch, how):
    for name in ("THALOVANT_ALARM_KEY_PREFIX", "THALOVANT_RECORDS_KEY_PREFIX"):
        monkeypatch.delenv(name, raising=False)
    prefix = "hub-0f8e6e0e-4e2b:memory"
    settings = {}
    if how == "setting":
        settings["key_prefix"] = prefix
    elif how == "own-env":
        monkeypatch.setenv("THALOVANT_ALARM_KEY_PREFIX", prefix)
    else:
        monkeypatch.setenv("THALOVANT_RECORDS_KEY_PREFIX", prefix)
    server = fakeredis.FakeServer()
    store = build_on(server, monkeypatch, settings)
    assert store.key_prefix == prefix
    store.save_changes([], [rec("anna", "1"), rec("anna", "2")])
    assert store.migrate_legacy(LegacyDocument([rec("ben", "1")])) == 1
    found = names(server)
    assert len(found) == 4, found
    assert all(n.startswith(f"{prefix}:records:v1:alarm:alarms:") for n in found), found
    assert f"{prefix}:records:v1:alarm:alarms:owners" in found
    assert f"{prefix}:records:v1:alarm:alarms:migration" in found
    assert by_id(store.load_all()) == by_id([rec("anna", "1"), rec("anna", "2"), rec("ben", "1")])


def test_the_setting_beats_its_own_environment_beats_the_shared_one(monkeypatch):
    monkeypatch.setenv("THALOVANT_ALARM_KEY_PREFIX", "own")
    monkeypatch.setenv("THALOVANT_RECORDS_KEY_PREFIX", "shared")
    server = fakeredis.FakeServer()
    assert build_on(server, monkeypatch, {"key_prefix": "setting"}).key_prefix == "setting"
    assert build_on(server, monkeypatch).key_prefix == "own"
    monkeypatch.delenv("THALOVANT_ALARM_KEY_PREFIX")
    assert build_on(server, monkeypatch).key_prefix == "shared"


def test_two_prefixes_on_one_redis_never_meet(monkeypatch):
    server = fakeredis.FakeServer()
    one = build_on(server, monkeypatch, {"key_prefix": "hub-1:memory"})
    two = build_on(server, monkeypatch, {"key_prefix": "hub-1:memory2"})
    three = build_on(server, monkeypatch, {"key_prefix": "hub-1"})
    one.save_changes([], [rec("anna", "1", where="one")])
    two.save_changes([], [rec("anna", "1", where="two")])
    assert one.load_all() == [rec("anna", "1", where="one")]
    assert two.load_all() == [rec("anna", "1", where="two")]
    assert three.load_all() == []


GOOD_PREFIXES = ["a", "hub-1:memory", "a.b-c_d:e", "x" * 200, "hub-0f8e6e0e-4e2b-4a0c-9b6c:skills"]
BAD_PREFIXES = [
    "", " ", "a b", "a*", "a?", "a[1]", "{a}", "a:", ":a", "a::b", "a\n", "é", "x" * 201, "a/b",
    "a%3Ab", "a\0b",
]
# Spaces around a setting are trimmed, so these two are only bad to the validator, not as settings.
TRIMMED = {" ", "a\n"}


@pytest.mark.parametrize("prefix", GOOD_PREFIXES)
def test_a_usable_prefix_is_accepted(prefix, monkeypatch):
    assert valid_key_prefix(prefix)
    server = fakeredis.FakeServer()
    store = build_on(server, monkeypatch, {"key_prefix": prefix})
    store.save_changes([], [rec("anna", "1")])
    assert all(n.startswith(f"{prefix}:records:v1:") for n in names(server))


@pytest.mark.parametrize("prefix", [p for p in BAD_PREFIXES if p and p not in TRIMMED])
def test_an_unusable_prefix_turns_redis_off_and_says_so_once(prefix, monkeypatch, caplog):
    assert not valid_key_prefix(prefix)
    server = fakeredis.FakeServer()
    store = build_on(server, monkeypatch, {"key_prefix": prefix})
    with caplog.at_level("WARNING", logger="thalovant_skillkit.records"):
        assert store.load_all() is None
        assert store.save_changes([], [rec("anna", "1")]) == Changes()
        assert store.load_all() is None
    assert names(server) == [], "nothing was written under any key"
    messages = [r.getMessage() for r in caplog.records if "key prefix" in r.getMessage()]
    assert len(messages) == 1, messages


def test_the_validator_refuses_every_bad_prefix():
    assert not any(valid_key_prefix(p) for p in BAD_PREFIXES)


def test_an_empty_prefix_is_the_default_not_an_error(monkeypatch):
    monkeypatch.delenv("THALOVANT_RECORDS_KEY_PREFIX", raising=False)
    store = build_on(fakeredis.FakeServer(), monkeypatch, {"key_prefix": "  "})
    assert store.key_prefix == "thalovant" and not valid_key_prefix("")


def test_a_bad_prefix_leaves_postgres_working(tmp_path, monkeypatch):
    path = str(tmp_path / "pg.sqlite")
    monkeypatch.setattr(
        JsonStateStore, "_redis_client", lambda self: fakeredis.FakeStrictRedis()
    )
    store = RecordStore(
        SCOPE, {"redis_url": "redis://x", "database_url": "postgresql://x", "key_prefix": "a b"},
        env_prefix="X", default_key=KEY,
    )
    store._backends = [PostgresBackend(lambda: PgOverSqlite(path), SCOPE, KEY)]
    store._built = True
    store.save_changes([], [rec("anna", "1")])
    assert store.load_all() == [rec("anna", "1")]


# ---- a Redis that says no -----------------------------------------------------------------------


class DeniedRedis:
    """A client whose Redis refuses everything, as an ACL does (`NOPERM`)."""

    def __init__(self, error):
        self._error = error

    def register_script(self, body):
        def call(*args, **kwargs):
            raise self._error

        return call

    def _refuse(self, *args, **kwargs):
        raise self._error

    smembers = hgetall = get = set = _refuse


def denied(message="No permissions to access a key", kind=None):
    redis = pytest.importorskip("redis")
    return (kind or redis.exceptions.NoPermissionError)(message)


def test_a_refusal_by_redis_is_logged_once_with_the_prefix_and_the_commands(caplog):
    backend = RedisBackend(DeniedRedis(denied()), SCOPE, KEY, "hub-1:memory")
    store = RecordStore(SCOPE, {}, env_prefix="X", default_key=KEY, backends=[backend])
    with caplog.at_level("WARNING", logger="thalovant_skillkit.records"):
        for _ in range(3):
            assert store.load_all() is None
            assert store.load_owner("anna") is None
        for _ in range(2):
            with pytest.raises(RecordStoreError) as raised:
                store.save_changes([], [rec("anna", "1")])
            assert raised.value.acl
        assert store.load_all_with_legacy(LegacyDocument([rec("anna", "1")])) is None
        assert store.load_all_with_legacy(LegacyDocument([rec("anna", "1")])) is None
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1, warnings
    text = warnings[0]
    assert "hub-1:memory:records:v1:" in text and "ACL" in text and "NoPermissionError" in text
    assert "~hub-1:memory:*" in text and "key_prefix" in text
    assert all(command in text for command in REDIS_ACL_COMMANDS)


def test_other_failures_still_warn_each_time(caplog):
    backend = RedisBackend(DeniedRedis(OSError("connection reset")), SCOPE, KEY)
    store = RecordStore(SCOPE, {}, env_prefix="X", default_key=KEY, backends=[backend])
    with caplog.at_level("WARNING", logger="thalovant_skillkit.records"):
        for _ in range(3):
            assert store.load_all() is None
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 3


@pytest.mark.parametrize(
    "message",
    ["WRONGPASS invalid username-password pair", "NOAUTH Authentication required"],
)
def test_a_wrong_password_is_told_with_the_same_hint(message, caplog):
    backend = RedisBackend(DeniedRedis(denied(message, kind=ConnectionError)), SCOPE, KEY)
    store = RecordStore(SCOPE, {}, env_prefix="X", default_key=KEY, backends=[backend])
    with caplog.at_level("WARNING", logger="thalovant_skillkit.records"):
        store.load_all()
        store.load_all()
    warnings = [r.getMessage() for r in caplog.records]
    assert len(warnings) == 1 and "ACL" in warnings[0] and "password" in warnings[0]


def test_postgres_still_serves_when_redis_refuses(tmp_path, caplog):
    cache = RedisBackend(DeniedRedis(denied()), SCOPE, KEY, "hub-1:memory")
    durable = PostgresBackend(lambda: PgOverSqlite(str(tmp_path / "pg.sqlite")), SCOPE, KEY)
    store = RecordStore(SCOPE, {}, env_prefix="X", default_key=KEY, backends=[cache, durable])
    with caplog.at_level("WARNING", logger="thalovant_skillkit.records"):
        with pytest.raises(RecordStoreError):
            store.save_changes([], [rec("anna", "1")])
        assert store.load_all() == [rec("anna", "1")], "PostgreSQL took it and serves it"
        with pytest.raises(RecordStoreError):
            store.save_changes([rec("anna", "1")], [rec("anna", "1", due=2)])
    assert len([r for r in caplog.records if "ACL" in r.getMessage()]) == 1


def test_a_redis_user_limited_by_an_acl_works_with_a_prefix_inside_it_and_says_no_outside():
    """A real Redis, a user that may touch only `hub-1:*` and run only the documented commands."""
    url = os.environ.get("THALOVANT_RECORDS_TEST_REDIS_URL")
    if not url:
        pytest.skip("no THALOVANT_RECORDS_TEST_REDIS_URL")
    import logging
    import urllib.parse

    import redis

    admin = redis.Redis.from_url(url)
    admin.flushdb()
    password = "p@ss:w/rd+1#?%"  # every character that breaks an unescaped URL
    admin.acl_setuser(
        "hubuser", enabled=True, passwords=[f"+{password}"], keys=["hub-1:*"],
        commands=["-@all"] + [f"+{c.lower().replace(' ', '|')}" for c in REDIS_ACL_COMMANDS],
        reset=True,
    )
    base = urllib.parse.urlsplit(url)
    escaped = urllib.parse.quote(password, safe="")
    # database 0 here; a URL naming another database also needs SELECT, which the list has.
    limited = f"redis://hubuser:{escaped}@{base.hostname}:{base.port}/{base.path.strip('/') or 0}"
    try:
        inside = RecordStore(
            "live",
            {"redis_url": limited, "key_prefix": "hub-1:memory"},
            env_prefix="THALOVANT_LIVE",
            default_key="things",
        )
        records = [rec("anna", "1", due=1), rec("anna", "2"), rec("ben", "1")]
        assert inside.load_all_with_legacy(LegacyDocument([rec("anna", "9")])) == [rec("anna", "9")]
        inside.save_changes([rec("anna", "9")], records)
        assert by_id(inside.load_all()) == by_id(records)
        assert by_id(inside.load_owner("anna")) == by_id(records[:2])
        inside.save_changes(records, records[:1])
        assert inside.load_all() == records[:1] and inside.owners() == [owner_key("anna")]
        assert all(k.decode().startswith("hub-1:memory:records:v1:") for k in admin.keys("*"))
        # The default prefix is outside the user's keys: NOPERM, said once; the skill falls back.
        records_log = logging.getLogger("thalovant_skillkit.records")
        seen: list[str] = []
        handler = logging.Handler()
        handler.emit = lambda record: seen.append(record.getMessage())  # type: ignore[method-assign]
        records_log.addHandler(handler)
        try:
            outside = RecordStore(
                "live", {"redis_url": limited}, env_prefix="THALOVANT_LIVE", default_key="things"
            )
            assert outside.load_all() is None and outside.load_all() is None
            with pytest.raises(RecordStoreError) as raised:
                outside.save_changes([], [rec("anna", "1")])
            assert raised.value.acl
        finally:
            records_log.removeHandler(handler)
        hints = [m for m in seen if "ACL" in m]
        assert len(hints) == 1 and "thalovant:records:v1:" in hints[0], seen
    finally:
        admin.acl_deluser("hubuser")
        admin.flushdb()


def test_the_shared_redis_url_sits_between_the_skills_own_and_the_generic_one(monkeypatch):
    for name in ("THALOVANT_ALARM_REDIS_URL", "THALOVANT_RECORDS_REDIS_URL", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)

    def url(settings=None):
        store = RecordStore(SCOPE, settings or {}, env_prefix="THALOVANT_ALARM", default_key=KEY)
        return store._config.redis_url

    assert url() == ""
    monkeypatch.setenv("REDIS_URL", "redis://generic")
    assert url() == "redis://generic"
    monkeypatch.setenv("THALOVANT_RECORDS_REDIS_URL", "redis://shared")
    assert url() == "redis://shared"
    monkeypatch.setenv("THALOVANT_ALARM_REDIS_URL", "redis://own")
    assert url() == "redis://own"
    assert url({"redis_url": "redis://setting"}) == "redis://setting"
    monkeypatch.delenv("THALOVANT_ALARM_REDIS_URL")
    assert url({"redis_url": "redis://setting"}) == "redis://setting"

