"""Per-owner record persistence for skills that keep a person's records.

`JsonStateStore` keeps every owner's records as ONE document under ONE key and
writes all of it back on each save. Two people (or two hub pods) saving at the
same moment overwrite one another, and each pod's copy goes stale. `RecordStore`
keeps the same records one at a time, under the person who owns them:

    store = RecordStore("alarm", settings, env_prefix="THALOVANT_ALARM",
                        default_key="alarms")
    records = store.load_all_with_legacy()      # at start; None = keep settings
    ...
    store.save_changes(before, after)           # writes only what changed

Where the data lives, chosen from the same settings and environment names as
`JsonStateStore` (`redis_url`, `redis_sentinel_urls`, `database_url`, and
`<PREFIX>_REDIS_URL`/`REDIS_URL`, `<PREFIX>_DATABASE_URL`/`DATABASE_URL`,
`<PREFIX>_STATE_KEY`), so an operator changes nothing:

* Redis, a HASH per owner (`thalovant:records:v1:<scope>:<key>:<owner key>`,
  field = the record's id, value = its JSON) and a SET of the owner keys, every
  write one Lua step.
* PostgreSQL, a row per record in `thalovant_records`, upserted and deleted by
  primary key in one transaction.
* With both set, Redis is read first and PostgreSQL keeps a copy; a Redis that
  came back empty is refilled from it.
* With neither, `load_all` returns None and `save_changes` does nothing: the
  skill keeps its own settings, exactly as before.

Redis keys start with `thalovant` unless the operator sets a key prefix
(`key_prefix`, `<PREFIX>_KEY_PREFIX` or `THALOVANT_RECORDS_KEY_PREFIX`), so a
Redis user whose ACL allows only `hub-<id>:*` can be given `hub-<id>:memory`.
A refusal by Redis's ACL or password is logged once, with the hint, and the
skill keeps its settings.

An owner is a label (the hub connection's), turned into a 40-hex key by hashing
(`owner_key`): no separator from a label ever reaches a key or a row, so "a" and
"a:b", an empty label, unicode or a megabyte of text cannot reach another
owner's records. A record with no owner field lives in the fixed `_unowned`
bucket.

What it does not do: it is last-writer-wins for a record changed by two pods at
once, and there is no transaction across records. Redis Cluster is not
supported (the scripts touch two keys).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from thalovant_skillkit.storage import JsonStateStore

LOG = logging.getLogger(__name__)

#: Every key and the table names carry this, so the layout can change without touching old data.
DEFAULT_KEY_PREFIX = "thalovant"
PREFIX = f"{DEFAULT_KEY_PREFIX}:records:v1"
TABLE = "thalovant_records"
META_TABLE = "thalovant_records_meta"
_SALT = b"thalovant-records/v1\0"

#: A key prefix is colon-separated words of these characters: what a Redis ACL pattern such as
#: `~hub-<id>:memory:*` can be written for, with nothing a glob or a script could read as more.
_KEY_PREFIX = re.compile(r"[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+)*\Z")
MAX_KEY_PREFIX = 200

#: What the Redis backend asks of Redis, for an operator who limits the user with an ACL
#: (`ACL SETUSER <user> on ><password> ~<prefix>:* -@all +evalsha +script|load ...`).
#: The Lua scripts call HSET, HSETNX, HDEL, HLEN, SADD and SREM; the reads are HGETALL and
#: SMEMBERS; the migration marker is GET and SET (with NX and EX); EVALSHA runs the scripts and
#: SCRIPT LOAD is how the client puts them in once per Redis start. SELECT is only sent when the
#: URL names a database other than 0.
REDIS_ACL_COMMANDS = (
    "EVALSHA", "SCRIPT LOAD", "HSET", "HSETNX", "HDEL", "HLEN", "HGETALL", "SADD", "SREM",
    "SMEMBERS", "GET", "SET", "SELECT",
)

#: The bucket of a record with no owner field. Not a hash, so it cannot be an owner's key.
UNOWNED = "_unowned"

#: One record's JSON, at most (a record is a person's alarm, not a document).
MAX_BODY_BYTES = 64 * 1024

#: How long one pod's claim to migrate stays valid before another may take it over.
MIGRATION_CLAIM_SECONDS = 300

#: A pod that finds no legacy document looks again after this long, not on every load.
LEGACY_RECHECK_SECONDS = 300.0


class RecordStoreError(Exception):
    """Records could not be read or written.

    `acl` is True when Redis refused the user or the key (a wrong password, or an ACL that does not
    allow these keys or commands): the store has already logged that, once, with the hint.

    A save that raises this has not been made as a whole: the caller keeps its
    in-memory change, logs, and tries again at its next save (compare with the
    snapshot it last persisted, so the same change is sent again).
    """

    def __init__(self, message: str = "", *, acl: bool = False):
        super().__init__(message)
        self.acl = acl


def owner_key(label: Any) -> str:
    """An owner's key: the label, hashed.

    No separator from the label reaches a key or a row, whatever it holds, and
    the key is the same fixed size whatever its length.
    """
    return hashlib.sha256(_SALT + str(label).encode("utf-8", "surrogatepass")).hexdigest()[:40]


@dataclass(frozen=True)
class Changes:
    """What a `save_changes` wrote: records put (added or changed) and deleted."""

    puts: int = 0
    deletes: int = 0


def valid_key_prefix(prefix: Any) -> bool:
    """Whether `prefix` can be a key prefix: words of letters, digits, `_`, `.` and `-` joined
    by single colons, at most 200 characters (so no glob, space, brace, empty segment or
    trailing colon)."""
    return (
        isinstance(prefix, str)
        and 0 < len(prefix) <= MAX_KEY_PREFIX
        and _KEY_PREFIX.match(prefix) is not None
    )


_ACL_ERRORS = {"NoPermissionError", "AuthenticationError", "AuthenticationWrongNumberOfArgsError"}
_ACL_TEXT = ("NOPERM", "WRONGPASS", "NOAUTH", "NO PERMISSIONS", "INVALID USERNAME-PASSWORD")


def _is_acl_error(error: BaseException) -> bool:
    """Redis said no to who we are or what we asked for, rather than being down."""
    if type(error).__name__ in _ACL_ERRORS:
        return True
    text = str(error).upper()
    return any(marker in text for marker in _ACL_TEXT)


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _body(record: Any) -> str:
    try:
        body = json.dumps(record, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise RecordStoreError(f"a record is not JSON: {error}") from error
    try:
        size = len(body.encode("utf-8"))
    except UnicodeEncodeError as error:  # a lone surrogate: no database stores it
        raise RecordStoreError(f"a record is not valid text: {error}") from error
    if size > MAX_BODY_BYTES:
        raise RecordStoreError(f"a record is over {MAX_BODY_BYTES} bytes")
    return body


# -- the backends ------------------------------------------------------------------------------
#
# A backend works in (owner key, record id, JSON body) and knows nothing of owners'
# labels. `apply` makes the puts and the deletes (each record on its own, atomically);
# `put_if_absent` is the migration's write. Anything that goes wrong is raised.


class MemoryBackend:
    """A dict behind a lock: what the kit's fake store and the tests run on.

    `fail` set to an exception makes the next calls raise it, to rehearse a
    database that is down.
    """

    def __init__(self) -> None:
        self.data: dict[str, dict[str, str]] = {}
        self.meta: dict[str, str] = {}
        self.calls = 0
        self.fail: Exception | None = None
        self._lock = threading.RLock()

    def _enter(self) -> None:
        self.calls += 1
        if self.fail is not None:
            raise self.fail

    name = "memory"

    def load_all(self) -> list[tuple[str, str, str]]:
        with self._lock:
            self._enter()
            return [(ok, rid, body) for ok, held in self.data.items() for rid, body in held.items()]

    def load_owner(self, ok: str) -> list[tuple[str, str, str]]:
        with self._lock:
            self._enter()
            return [(ok, rid, body) for rid, body in (self.data.get(ok) or {}).items()]

    def owners(self) -> list[str]:
        with self._lock:
            self._enter()
            return sorted(ok for ok, held in self.data.items() if held)

    def apply(self, puts: list[tuple[str, str, str]], deletes: list[tuple[str, str]]) -> None:
        with self._lock:
            self._enter()
            for ok, rid, body in puts:
                self.data.setdefault(ok, {})[rid] = body
            for ok, rid in deletes:
                held = self.data.get(ok)
                if held is not None:
                    held.pop(rid, None)
                    if not held:
                        del self.data[ok]

    def put_if_absent(self, items: list[tuple[str, str, str]]) -> int:
        with self._lock:
            self._enter()
            added = 0
            for ok, rid, body in items:
                held = self.data.setdefault(ok, {})
                if rid not in held:
                    held[rid] = body
                    added += 1
            return added

    def migration_state(self) -> str:
        with self._lock:
            self._enter()
            value = self.meta.get("migration", "")
            return "none" if not value else ("done" if value == "done" else "running")

    def migration_claim(self, token: str, ttl: float) -> bool:
        with self._lock:
            self._enter()
            current = self.meta.get("migration", "")
            if current == "done":
                return False
            if current.startswith("running:"):
                _, _, started = current.split(":", 2)
                if time.time() - float(started) < ttl:
                    return False
            self.meta["migration"] = f"running:{token}:{time.time()}"
            return True

    def migration_finish(self) -> None:
        with self._lock:
            self._enter()
            self.meta["migration"] = "done"


#: KEYS: owner hash, owner set. ARGV: id, body, owner key.
_PUT = """
redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
redis.call('SADD', KEYS[2], ARGV[3])
return 1
"""
#: KEYS: owner hash, owner set. ARGV: id, body, owner key. Returns 1 when the record was new.
_PUT_NX = """
local added = redis.call('HSETNX', KEYS[1], ARGV[1], ARGV[2])
redis.call('SADD', KEYS[2], ARGV[3])
return added
"""
#: KEYS: owner hash, owner set. ARGV: id, owner key.
#: The owner leaves the set with their last record.
_DELETE = """
local gone = redis.call('HDEL', KEYS[1], ARGV[1])
if redis.call('HLEN', KEYS[1]) == 0 then redis.call('SREM', KEYS[2], ARGV[2]) end
return gone
"""


class RedisBackend:
    """A HASH per owner and a SET of the owners, changed by one Lua step per record.

        <prefix>:records:v1:<scope>:<key>:<owner key>   HASH id -> JSON body
        <prefix>:records:v1:<scope>:<key>:owners        SET  owner keys
        <prefix>:records:v1:<scope>:<key>:migration     STRING  running:<token> | done

    `<prefix>` is `thalovant` unless the operator sets a key prefix (so a Redis user limited to
    `hub-<id>:*` can be given `hub-<id>:memory`). `scope` and `key` are percent-encoded, so no
    pair of them can spell another's keys.
    """

    name = "redis"

    def __init__(self, client: Any, scope: str, key: str, prefix: str = DEFAULT_KEY_PREFIX):
        if not valid_key_prefix(prefix):
            raise ValueError(f"not a usable key prefix: {prefix!r}")
        self._client = client
        self.prefix = prefix
        self.namespace = f"{prefix}:records:v1:"
        self._base = f"{self.namespace}{quote(scope, safe='')}:{quote(key, safe='')}"
        self._scripts = {
            name: client.register_script(body)
            for name, body in (("put", _PUT), ("put_nx", _PUT_NX), ("delete", _DELETE))
        }

    def _hash(self, ok: str) -> str:
        return f"{self._base}:{ok}"

    @property
    def _owners(self) -> str:
        return f"{self._base}:owners"

    @property
    def _marker(self) -> str:
        return f"{self._base}:migration"

    def owners(self) -> list[str]:
        return sorted(_text(member) for member in self._client.smembers(self._owners))

    def load_owner(self, ok: str) -> list[tuple[str, str, str]]:
        raw = self._client.hgetall(self._hash(ok))
        return [(ok, _text(rid), _text(body)) for rid, body in raw.items()]

    def load_all(self) -> list[tuple[str, str, str]]:
        found: list[tuple[str, str, str]] = []
        for ok in self.owners():
            found.extend(self.load_owner(ok))
        return found

    def apply(self, puts: list[tuple[str, str, str]], deletes: list[tuple[str, str]]) -> None:
        for ok, rid, body in puts:
            self._scripts["put"](keys=[self._hash(ok), self._owners], args=[rid, body, ok])
        for ok, rid in deletes:
            self._scripts["delete"](keys=[self._hash(ok), self._owners], args=[rid, ok])

    def put_if_absent(self, items: list[tuple[str, str, str]]) -> int:
        added = 0
        for ok, rid, body in items:
            added += int(
                self._scripts["put_nx"](keys=[self._hash(ok), self._owners], args=[rid, body, ok])
            )
        return added

    def migration_state(self) -> str:
        value = self._client.get(self._marker)
        if value is None:
            return "none"
        return "done" if _text(value) == "done" else "running"

    def migration_claim(self, token: str, ttl: float) -> bool:
        return bool(self._client.set(self._marker, f"running:{token}", nx=True, ex=int(ttl)))

    def migration_finish(self) -> None:
        self._client.set(self._marker, "done")


_SCHEMA = (
    f"create table if not exists {TABLE} ("
    "seq bigserial, scope text not null, key text not null, "
    "owner_key text not null, id text not null, "
    "body jsonb not null, updated_at timestamptz not null default now(), "
    "primary key (scope, key, owner_key, id))",
    f"create index if not exists {TABLE}_seq on {TABLE} (scope, key, seq)",
    f"create table if not exists {META_TABLE} ("
    "scope text not null, key text not null, name text not null, state text not null, "
    "at timestamptz not null default now(), primary key (scope, key, name))",
)


class PostgresBackend:
    """A row per record. Puts and deletes of one save are one transaction; every
    statement is parameterised; the tables are made once, under an advisory lock
    (two pods starting together would race on `create table if not exists`).

    `connect()` returns a psycopg-style connection (`cursor()`, `transaction()`,
    `close()`): one per backend, used under a lock and dropped, then made again
    on the next call, when anything fails.
    """

    name = "postgres"

    def __init__(self, connect: Callable[[], Any], scope: str, key: str):
        self._connect = connect
        self._scope, self._key = scope, key
        self._lock = threading.RLock()
        self._conn: Any = None
        self._ready = False

    def _run(self, work: Callable[[Any], Any]) -> Any:
        with self._lock:
            try:
                if self._conn is None:
                    self._conn, self._ready = self._connect(), False
                if not self._ready:
                    with self._conn.transaction():
                        cursor = self._conn.cursor()
                        cursor.execute(
                            "select pg_advisory_xact_lock(hashtextextended(%s, 0))", (TABLE,)
                        )
                        for statement in _SCHEMA:
                            cursor.execute(statement)
                    self._ready = True
                with self._conn.transaction():
                    return work(self._conn.cursor())
            except Exception:
                with suppress(Exception):
                    if self._conn is not None:
                        self._conn.close()
                self._conn = None
                raise

    @staticmethod
    def _as_text(body: Any) -> str:
        return (
            body
            if isinstance(body, str)
            else json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        )

    def owners(self) -> list[str]:
        def work(cur):
            cur.execute(
                f"select distinct owner_key from {TABLE} "
                "where scope = %s and key = %s order by owner_key",
                (self._scope, self._key),
            )
            return [row[0] for row in cur.fetchall()]

        return self._run(work)

    def load_owner(self, ok: str) -> list[tuple[str, str, str]]:
        def work(cur):
            cur.execute(
                f"select id, body from {TABLE} "
                "where scope = %s and key = %s and owner_key = %s order by seq",
                (self._scope, self._key, ok),
            )
            return [(ok, row[0], self._as_text(row[1])) for row in cur.fetchall()]

        return self._run(work)

    def load_all(self) -> list[tuple[str, str, str]]:
        def work(cur):
            cur.execute(
                f"select owner_key, id, body from {TABLE} "
                "where scope = %s and key = %s order by seq",
                (self._scope, self._key),
            )
            return [(row[0], row[1], self._as_text(row[2])) for row in cur.fetchall()]

        return self._run(work)

    def apply(self, puts: list[tuple[str, str, str]], deletes: list[tuple[str, str]]) -> None:
        def work(cur):
            for ok, rid, body in puts:
                cur.execute(
                    f"insert into {TABLE} (scope, key, owner_key, id, body, updated_at) "
                    "values (%s, %s, %s, %s, %s::jsonb, now()) "
                    "on conflict (scope, key, owner_key, id) "
                    "do update set body = excluded.body, updated_at = now()",
                    (self._scope, self._key, ok, rid, body),
                )
            for ok, rid in deletes:
                cur.execute(
                    f"delete from {TABLE} "
                    "where scope = %s and key = %s and owner_key = %s and id = %s",
                    (self._scope, self._key, ok, rid),
                )

        self._run(work)

    def put_if_absent(self, items: list[tuple[str, str, str]]) -> int:
        def work(cur):
            added = 0
            for ok, rid, body in items:
                cur.execute(
                    f"insert into {TABLE} (scope, key, owner_key, id, body, updated_at) "
                    "values (%s, %s, %s, %s, %s::jsonb, now()) "
                    "on conflict (scope, key, owner_key, id) do nothing returning id",
                    (self._scope, self._key, ok, rid, body),
                )
                if cur.fetchone() is not None:
                    added += 1
            return added

        return self._run(work)

    def _meta(self, cur) -> tuple[str, float] | None:
        cur.execute(
            f"select state, extract(epoch from at) from {META_TABLE} "
            "where scope = %s and key = %s and name = 'migration'",
            (self._scope, self._key),
        )
        row = cur.fetchone()
        return None if row is None else (row[0], float(row[1]))

    def migration_state(self) -> str:
        def work(cur):
            meta = self._meta(cur)
            return "none" if meta is None else ("done" if meta[0] == "done" else "running")

        return self._run(work)

    def migration_claim(self, token: str, ttl: float) -> bool:
        def work(cur):
            cur.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{META_TABLE}:{self._scope}:{self._key}",),
            )
            meta = self._meta(cur)
            now = time.time()
            if meta is not None:
                if meta[0] == "done" or now - meta[1] < ttl:
                    return False
                cur.execute(
                    f"update {META_TABLE} set state = %s, at = to_timestamp(%s) "
                    "where scope = %s and key = %s and name = 'migration'",
                    (f"running:{token}", now, self._scope, self._key),
                )
                return True
            cur.execute(
                f"insert into {META_TABLE} (scope, key, name, state, at) "
                "values (%s, %s, 'migration', %s, to_timestamp(%s))",
                (self._scope, self._key, f"running:{token}", now),
            )
            return True

        return bool(self._run(work))

    def migration_finish(self) -> None:
        def work(cur):
            cur.execute(
                f"update {META_TABLE} set state = 'done', at = now() "
                "where scope = %s and key = %s and name = 'migration'",
                (self._scope, self._key),
            )

        self._run(work)


def _psycopg_connect(database_url: str) -> Any:
    import psycopg

    return psycopg.connect(database_url, connect_timeout=2, autocommit=True)


# -- the store ---------------------------------------------------------------------------------


class RecordStore:
    """A skill's records, kept per owner and written one at a time.

    `scope`, `settings`, `env_prefix` and `default_key` are `JsonStateStore`'s,
    read the same way, so the same settings and environment turn it on. The
    records are dicts with an id (`id_field`) and an owner (`owner_field`); a
    record with no id gets one made from its content (so a changed record then
    counts as one removed and one added, which is the same on disk).

    `backends` replaces what the settings ask for: used by the kit's fake store
    and by tests.
    """

    def __init__(
        self,
        scope: str,
        settings: dict,
        *,
        env_prefix: str,
        default_key: str,
        owner_field: str = "owner",
        id_field: str = "id",
        backends: Iterable[Any] | None = None,
    ):
        self.scope = scope
        self.owner_field, self.id_field = owner_field, id_field
        self._config = JsonStateStore(
            scope, settings, env_prefix=env_prefix, default_key=default_key
        )
        self.key = self._config.key
        # One variable for every record skill in a runtime, between the skill's own and the
        # generic REDIS_URL (which other software in the pod may mean differently).
        shared_url = os.getenv("THALOVANT_RECORDS_REDIS_URL", "").strip()
        if (
            shared_url
            and not settings.get("redis_url")
            and not os.getenv(f"{env_prefix}_REDIS_URL")
        ):
            self._config.redis_url = shared_url
            # JsonStateStore decided `enabled` before this URL existed, and every record
            # skill asks it first.
            self._config.enabled = True
        # Where in Redis: the setting, then `<PREFIX>_KEY_PREFIX`, then
        # THALOVANT_RECORDS_KEY_PREFIX, else `thalovant` (the keys then are what 0.31.0 wrote).
        raw = (
            settings.get("key_prefix")
            or os.getenv(f"{env_prefix}_KEY_PREFIX")
            or os.getenv("THALOVANT_RECORDS_KEY_PREFIX")
            or ""
        )
        self.key_prefix = str(raw).strip() or DEFAULT_KEY_PREFIX
        self._acl_warned = False
        self._backends: list[Any] | None = list(backends) if backends is not None else None
        self._built = backends is not None
        self._build_lock = threading.Lock()
        self._legacy_checked = 0.0
        self._legacy_refused = False

    # -- what is configured --------------------------------------------------------

    def _backend_list(self) -> list[Any]:
        if self._built:
            return self._backends or []
        with self._build_lock:
            if not self._built:
                found: list[Any] = []
                config = self._config
                if config.redis_url or config.redis_sentinel_urls:
                    if not valid_key_prefix(self.key_prefix):
                        LOG.warning(
                            "record store %s: %r is not a usable key prefix (colon-separated words "
                            "of letters, digits, _ . -); Redis is not used",
                            self.scope,
                            self.key_prefix,
                        )
                    else:
                        client = (
                            config._redis_client()
                        )  # the kit's builder: URL options, Sentinel, short timeouts
                        if client is not None:
                            found.append(
                                RedisBackend(client, self.scope, self.key, self.key_prefix)
                            )
                if config.database_url:
                    url = config.database_url
                    found.append(
                        PostgresBackend(lambda: _psycopg_connect(url), self.scope, self.key)
                    )
                self._backends, self._built = found, True
        return self._backends or []

    @property
    def enabled(self) -> bool:
        """Whether a database is set up. Without one the skill keeps its settings."""
        if self._built:
            return bool(self._backends)
        return self._config.enabled

    # -- when Redis or PostgreSQL says no ------------------------------------------

    def _acl_hint(self, backend: Any) -> str:
        prefix = getattr(backend, "prefix", self.key_prefix)
        namespace = getattr(backend, "namespace", f"{prefix}:records:v1:")
        return (
            f"Redis refused the request. This store's keys are under {namespace!r}. If the Redis "
            f"user is limited by an ACL, it needs the key pattern ~{prefix}:* (or a key prefix "
            f"it may use: key_prefix or THALOVANT_RECORDS_KEY_PREFIX) and the commands "
            f"{', '.join(REDIS_ACL_COMMANDS)}; check the user and password too. Until then the "
            f"records stay in the skill's settings"
        )

    def _failed(self, backend: Any, what: str, error: BaseException) -> bool:
        """Log a backend's failure. A refusal by Redis's ACL or password is one WARNING with the
        hint, the first time, not on every call. Returns whether it was such a refusal."""
        if getattr(backend, "name", "") == "redis" and _is_acl_error(error):
            if not self._acl_warned:
                self._acl_warned = True
                LOG.warning(
                    "record store %s: %s (%s: %s)",
                    self.scope,
                    self._acl_hint(backend),
                    type(error).__name__,
                    error,
                )
            return True
        LOG.warning(
            "record store %s: %s %s failed (%s)",
            self.scope,
            backend.name,
            what,
            type(error).__name__,
        )
        return False

    # -- reading -------------------------------------------------------------------

    def _decode(self, rows: list[tuple[str, str, str]]) -> list[dict]:
        records: list[dict] = []
        for _, rid, body in rows:
            try:
                value = json.loads(body)
            except ValueError:
                LOG.warning("record store %s: a record of %r is not JSON; skipped", self.scope, rid)
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def load_all(self) -> list[dict] | None:
        """Every owner's records, or None when no database is set up or none answers
        (the caller keeps its settings). A Redis that answers empty while PostgreSQL
        holds records is refilled from it."""
        backends = self._backend_list()
        if not backends:
            return None
        answered = False
        rows: list[tuple[str, str, str]] = []
        warm: list[Any] = []
        for backend in backends:
            try:
                found = backend.load_all()
            except Exception as error:  # noqa: BLE001 - a backend that is down is skipped
                self._failed(backend, "load", error)
                continue
            answered = True
            if found:
                rows = found
                break
            warm.append(backend)
        if not answered:
            return None
        if rows and warm:
            for backend in warm:
                try:
                    backend.put_if_absent(rows)
                except Exception as error:  # noqa: BLE001 - a cache that cannot be refilled is only a cache
                    self._failed(backend, "refill", error)
        return self._decode(rows)

    def load_owner(self, owner: Any) -> list[dict] | None:
        """One owner's records (for a read at each turn), or None as `load_all`."""
        ok = UNOWNED if owner is None else owner_key(owner)
        backends = self._backend_list()
        if not backends:
            return None
        answered = False
        for backend in backends:
            try:
                rows = backend.load_owner(ok)
            except Exception as error:  # noqa: BLE001
                self._failed(backend, "load", error)
                continue
            answered = True
            if rows:
                return self._decode(rows)
        return [] if answered else None

    def owners(self) -> list[str]:
        """The keys (never the labels) of the owners who hold records."""
        for backend in self._backend_list():
            try:
                found = backend.owners()
            except Exception as error:  # noqa: BLE001
                self._failed(backend, "owners", error)
                continue
            if found:
                return found
        return []

    def splice_owner(self, records: list[dict], owner: Any, fresh: list[dict]) -> list[dict]:
        """`records` with this owner's records replaced by `fresh`; the others are kept as they
        are. No I/O: it is how a skill keeps both its working list and its persisted snapshot in
        step with what `load_owner` just read."""
        ok = UNOWNED if owner is None else owner_key(owner)
        return [r for r in records if self.owner_key_of(r) != ok] + list(fresh)

    def replace_owner(self, current: list[dict], owner: Any) -> list[dict] | None:
        """`current` with this owner's records read afresh. None when nothing could be read
        (keep `current`)."""
        fresh = self.load_owner(owner)
        return None if fresh is None else self.splice_owner(current, owner, fresh)

    # -- writing -------------------------------------------------------------------

    def owner_key_of(self, record: dict) -> str:
        """The key of the owner this record belongs to (`_unowned` when it has no owner field)."""
        owner = record.get(self.owner_field) if isinstance(record, dict) else None
        return UNOWNED if owner is None else owner_key(owner)

    def _id_of(self, record: dict, body: str) -> str:
        rid = record.get(self.id_field)
        if rid is None or str(rid) == "":
            return "~" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]
        return str(rid)

    def _index(self, records: Iterable[dict]) -> dict[tuple[str, str], tuple[dict, str]]:
        found: dict[tuple[str, str], tuple[dict, str]] = {}
        for record in records:
            if not isinstance(record, dict):
                raise RecordStoreError("a record is not a dict")
            body = _body(record)
            slot = (self.owner_key_of(record), self._id_of(record, body))
            if slot in found:
                LOG.warning(
                    "record store %s: two records share one id; the later one is kept", self.scope
                )
            found[slot] = (record, body)
        return found

    def changes(self, before: Iterable[dict], after: Iterable[dict]) -> tuple[list, list]:
        """What `save_changes` would write: the puts and the deletes, from the
        difference of the two lists by (owner, id)."""
        old, new = self._index(before), self._index(after)
        puts = [
            (ok, rid, body)
            for (ok, rid), (_, body) in new.items()
            if (ok, rid) not in old or old[(ok, rid)][1] != body
        ]
        deletes = [(ok, rid) for (ok, rid) in old if (ok, rid) not in new]
        return puts, deletes

    def save_changes(self, before: Iterable[dict], after: Iterable[dict]) -> Changes:
        """Write what differs between `before` (what was last persisted) and
        `after`: records added or changed are put, records gone are deleted, by
        (owner, id). Nothing else is read or written; other owners are untouched.

        Raises `RecordStoreError` when a backend could not take the change (the
        others are still tried). With no database set up it does nothing.
        """
        puts, deletes = self.changes(before, after)
        backends = self._backend_list()
        if not backends or not (puts or deletes):
            return Changes()
        failures: list[str] = []
        refused = False
        for backend in backends:
            try:
                backend.apply(puts, deletes)
            except Exception as error:  # noqa: BLE001 - reported below, the other backend is still tried
                acl = self._failed(backend, "save", error)
                refused = refused or acl
                failures.append(f"{backend.name}: {type(error).__name__}: {error}")
        if failures:
            raise RecordStoreError("; ".join(failures), acl=refused)
        return Changes(len(puts), len(deletes))

    # -- from the whole document ---------------------------------------------------

    def migrate_legacy(self, legacy: JsonStateStore | None = None) -> int:
        """Bring the old whole-document records into the per-owner layout, once.

        Safe by construction: the legacy document is only read; a record is put
        only if it is not already there, so whatever is newer wins; a claim in
        the first backend keeps two pods from both importing (a claim that is
        not finished within five minutes may be taken over, and the import is
        then simply repeated); and the marker is set only after a document was
        read and imported, so a legacy store that was merely unreachable is
        tried again. Returns how many records were put.
        """
        backends = self._backend_list()
        if not backends:
            return 0
        primary = backends[0]
        legacy = legacy or self._config
        try:
            if primary.migration_state() == "done":
                return 0
            now = time.monotonic()
            if self._legacy_refused:
                return 0
            if self._legacy_checked and now - self._legacy_checked < LEGACY_RECHECK_SECONDS:
                return 0
            document = legacy.load()
            if document is None:
                self._legacy_checked = now
                self._legacy_refused = bool(getattr(legacy, "redis_refused", False))
                return 0
            if not primary.migration_claim(uuid.uuid4().hex, MIGRATION_CLAIM_SECONDS):
                return 0
            rows = [
                (ok, rid, body)
                for (ok, rid), (_, body) in self._index(
                    r for r in document if isinstance(r, dict)
                ).items()
            ]
            imported = 0
            for index, backend in enumerate(backends):
                put = backend.put_if_absent(rows) if rows else 0
                imported = put if index == 0 else imported
            primary.migration_finish()
        except RecordStoreError:
            raise
        except Exception as error:  # noqa: BLE001
            refused = self._failed(primary, "migration", error)  # an ACL refusal: said once
            raise RecordStoreError(
                f"migrating the whole-document records: {type(error).__name__}: {error}",
                acl=refused,
            ) from error
        LOG.info(
            "record store %s: imported %d record(s) from the whole document", self.scope, imported
        )
        return imported

    def load_all_with_legacy(self, legacy: JsonStateStore | None = None) -> list[dict] | None:
        """`migrate_legacy` if still to do, then `load_all`: the usual call at a skill's start."""
        if not self.enabled:
            return None
        try:
            self.migrate_legacy(legacy)
        except RecordStoreError as error:
            if not error.acl:  # a refusal by Redis was logged, once, with its hint
                LOG.warning("record store %s: %s", self.scope, error)
        return self.load_all()
