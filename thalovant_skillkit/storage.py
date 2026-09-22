"""Optional shared JSON persistence for household skills.

Redis is the read-through cache and PostgreSQL is the fallback store. Keep the
existing fleet key and table format so adopting this helper needs no migration.
Drivers are imported only when configured; unconfigured skills stay local.
This is best-effort persistence, not a transaction across two backends. The
caller owns record validation, ownership, and local fallback storage.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
from typing import Any

LOG = logging.getLogger(__name__)


def redis_sentinel_urls(value: Any) -> list[tuple[str, int]]:
    urls: list[tuple[str, int]] = []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    for item in values:
        for raw_url in re.split(r"[\s,]+", str(item or "").strip()):
            if not raw_url:
                continue
            parsed = urllib.parse.urlsplit(raw_url if "://" in raw_url else f"redis://{raw_url}")
            if parsed.hostname:
                urls.append((parsed.hostname, parsed.port or 26379))
    return urls


def redis_url_options(redis_url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(redis_url or "")
    db = 0
    if parsed.path and parsed.path != "/":
        try:
            db = int(parsed.path.strip("/").split("/", 1)[0])
        except ValueError:
            db = 0
    options: dict[str, Any] = {"db": db}
    if parsed.username:
        options["username"] = urllib.parse.unquote(parsed.username)
    if parsed.password:
        options["password"] = urllib.parse.unquote(parsed.password)
    return options


class JsonStateStore:
    def __init__(self, scope: str, settings: dict, *, env_prefix: str, default_key: str):
        self.scope = scope
        self.key = str(
            settings.get("state_key") or os.getenv(f"{env_prefix}_STATE_KEY") or default_key
        )
        self.redis_url = str(settings.get("redis_url") or os.getenv(f"{env_prefix}_REDIS_URL")
                             or os.getenv("REDIS_URL") or "")
        self.redis_sentinel_urls = redis_sentinel_urls(
            settings.get("redis_sentinel_urls")
            or os.getenv(f"{env_prefix}_REDIS_SENTINEL_URLS")
            or os.getenv("REDIS_SENTINEL_URLS")
            or ""
        )
        self.redis_sentinel_service_name = str(
            settings.get("redis_sentinel_service_name")
            or os.getenv(f"{env_prefix}_REDIS_SENTINEL_SERVICE_NAME")
            or os.getenv("REDIS_SENTINEL_SERVICE_NAME")
            or "mymaster"
        )
        self.database_url = str(
            settings.get("database_url")
            or os.getenv(f"{env_prefix}_DATABASE_URL")
            or os.getenv("DATABASE_URL")
            or ""
        )
        self._redis = None
        self._pg = None
        self._pg_ready = False
        self.enabled = bool(self.redis_url or self.redis_sentinel_urls or self.database_url)

    def load(self) -> list[dict] | None:
        if not self.enabled:
            return None
        value = self._load_redis()
        if value is not None:
            return value
        value = self._load_postgres()
        if value is not None:
            self._save_redis(value)
        return value

    def save(self, value: list[dict]):
        if not self.enabled:
            return
        self._save_redis(value)
        self._save_postgres(value)

    def _redis_client(self):
        if not self.redis_url and not self.redis_sentinel_urls:
            return None
        if self._redis is None:
            try:
                if self.redis_sentinel_urls:
                    from redis.sentinel import Sentinel

                    options = redis_url_options(self.redis_url)
                    sentinel_kwargs = {
                        key: value
                        for key, value in options.items()
                        if key in {"username", "password"} and value
                    }
                    sentinel = Sentinel(
                        self.redis_sentinel_urls,
                        socket_timeout=0.2,
                        sentinel_kwargs=sentinel_kwargs,
                    )
                    self._redis = sentinel.master_for(
                        self.redis_sentinel_service_name,
                        socket_timeout=0.2,
                        socket_connect_timeout=0.2,
                        **options,
                    )
                else:
                    import redis

                    self._redis = redis.Redis.from_url(
                        self.redis_url, socket_timeout=0.2, socket_connect_timeout=0.2
                    )
            except Exception as error:
                LOG.warning("State store Redis state disabled: %s", error)
                self.redis_url = ""
                self.redis_sentinel_urls = []
                return None
        return self._redis

    def _load_redis(self) -> list[dict] | None:
        client = self._redis_client()
        if client is None:
            return None
        try:
            raw = client.get(self._store_key())
            return json.loads(raw) if raw else None
        except Exception as error:
            LOG.warning("State store Redis state load failed: %s", error)
            return None

    def _save_redis(self, value: list[dict]):
        client = self._redis_client()
        if client is None:
            return
        try:
            client.set(self._store_key(), json.dumps(value, separators=(",", ":")))
        except Exception as error:
            LOG.warning("State store Redis state save failed: %s", error)

    def _postgres(self):
        if not self.database_url:
            return None
        if self._pg is None:
            try:
                import psycopg

                self._pg = psycopg.connect(self.database_url, connect_timeout=1)
                self._pg.autocommit = True
            except Exception as error:
                LOG.warning("State store Postgres state disabled: %s", error)
                self.database_url = ""
                return None
        if not self._pg_ready:
            with self._pg.cursor() as cur:
                cur.execute(
                    "create table if not exists thalovant_skill_state "
                    "(scope text not null, key text not null, value jsonb not null, "
                    "updated_at timestamptz not null default now(), primary key(scope, key))"
                )
            self._pg_ready = True
        return self._pg

    def _load_postgres(self) -> list[dict] | None:
        try:
            conn = self._postgres()
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute("select value from thalovant_skill_state where scope=%s and key=%s",
                            (self.scope, self.key))
                row = cur.fetchone()
            return row[0] if row else None
        except Exception as error:
            LOG.warning("State store Postgres state load failed: %s", error)
            return None

    def _save_postgres(self, value: list[dict]):
        try:
            conn = self._postgres()
            if conn is None:
                return
            with conn.cursor() as cur:
                cur.execute(
                    "insert into thalovant_skill_state(scope, key, value, updated_at) "
                    "values(%s, %s, %s::jsonb, now()) "
                    "on conflict(scope, key) do update set value=excluded.value, updated_at=now()",
                    (self.scope, self.key, json.dumps(value, separators=(",", ":"))),
                )
        except Exception as error:
            LOG.warning("State store Postgres state save failed: %s", error)

    def _store_key(self) -> str:
        return f"thalovant:{self.scope}:{self.key}"
