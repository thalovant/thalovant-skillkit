Last Edit: Claude Code (Claude Opus 5.5) - 2026-11-07 - Motive: The import marker in every backend, PostgreSQL re-read after a Redis refusal, and the guide's example keeps an unsaved change (CodeRabbit findings on #52 and #54).
Previous:  Claude Code (Claude Opus 5.5) - 2026-11-06 - Motive: RecordStore uses no Lua, so a skill's Redis login needs no scripting right.

# Per-owner records (`thalovant_skillkit.records`)

A guide for skill authors: what `RecordStore` keeps and where, how an existing
skill that stands on `JsonStateStore` moves over, and what it does not do. The
reference entry is [reference.md](reference.md#per-owner-records); the code is
[`records.py`](../thalovant_skillkit/records.py), the tests
[`test_records.py`](../test/test_records.py).

## Why

`JsonStateStore` keeps every owner's records as one JSON document under one key
and writes all of it back on each save. With two people, or two hub pods,
saving at the same moment, the later write replaces the earlier one's change;
and a pod that read the document once at start works from a copy that goes
stale. The alarm, reminder, timer and stopwatch skills stand on it. `RecordStore`
keeps each record by itself, under the person who owns it, and a save writes only
the records that changed.

## What it keeps and where

It reads the same settings and environment as `JsonStateStore`, so an operator
changes nothing: `redis_url`, `redis_sentinel_urls`, `redis_sentinel_service_name`
and `database_url` in the skill's settings, then `<PREFIX>_REDIS_URL`,
`<PREFIX>_REDIS_SENTINEL_URLS`, `<PREFIX>_DATABASE_URL`, then `REDIS_URL`,
`REDIS_SENTINEL_URLS`, `DATABASE_URL`; `state_key` / `<PREFIX>_STATE_KEY` selects the
key (one per hub, if several share a database). `key_prefix` / `<PREFIX>_KEY_PREFIX` /
`THALOVANT_RECORDS_KEY_PREFIX` moves every Redis key (below); `THALOVANT_RECORDS_REDIS_URL` is one
Redis URL for every record skill in a runtime (after the skill's own `<PREFIX>_REDIS_URL`, before
the generic `REDIS_URL`).

| Backend | Layout |
|---|---|
| Redis | `<key prefix>:records:v1:<scope>:<key>:<owner key>` is a HASH, field = the record's id, value = its JSON. `<key prefix>:records:v1:<scope>:<key>:owners` is a SET of the owner keys. `...:migration` is the import marker. `<scope>` and `<key>` are percent-encoded. The key prefix is `thalovant` unless you set one (see the operator section below). Each record changes in one `MULTI` transaction; a delete also `WATCH`es the owner's hash. |
| PostgreSQL | Table `thalovant_records (seq, scope, key, owner_key, id, body jsonb, updated_at)`, primary key `(scope, key, owner_key, id)`; `thalovant_records_meta` holds its copy of the import marker. A save's puts and deletes are one transaction. Tables are created once, under an advisory lock. |
| Both | Redis is read first; PostgreSQL keeps a copy. A Redis that answers empty while PostgreSQL holds records is refilled from it. |
| Neither | `load_all()` is None and `save_changes` does nothing: the skill keeps its settings, as it did. |

**The owner is hashed.** `owner_key(label)` is the first 40 hex digits of
SHA-256 over a versioned prefix and the label, so no separator from a label ever
reaches a key or a row: "a" and "a:b", an empty label, unicode or a megabyte of
text cannot reach another owner's records. A record whose owner field is missing
or None lives in the fixed bucket `_unowned` (an empty-string owner is an owner,
not unowned). The label itself is only inside the record.

## The calls

| Call | Does |
|---|---|
| `load_all()` | Every owner's records, or None (no database, or none answered: keep the settings). |
| `load_owner(owner)` | One owner's records, or None; for a read at each turn. |
| `splice_owner(records, owner, fresh)` | A list with that owner's records replaced by `fresh`; no I/O. |
| `replace_owner(records, owner)` | `load_owner` then `splice_owner`; None if nothing could be read. |
| `save_changes(before, after)` | Diffs the two lists by (owner, id) and writes only the records added or changed (put) and the records gone (delete). Returns `Changes(puts, deletes)`. Raises `RecordStoreError` if a backend could not take it (the other is still tried). |
| `owners()` | The owner keys that hold records. Never labels. |
| `migrate_legacy(legacy=None)` / `load_all_with_legacy(legacy=None)` | Bring the old whole document over once (below). `legacy` defaults to the kit's own `JsonStateStore` for the same scope and key. |

A record without an id gets one made from its content, so changing it counts as
one removed and one added (the same thing on disk). A record is at most 64 KB of
JSON and must be valid text.

## Moving a skill over

The skills hold their records as a list of dicts in `self.settings[...]` and call
`_state_store().load()` and `.save(list)`. The change is small and keeps the
settings as the local fallback:

```python
import copy
from thalovant_skillkit.records import RecordStore, RecordStoreError

def initialize(self):                              # or __init__: before the first _load()
    self._records = None                           # the store, made at first use
    self._persisted = []
    self._load()

def _store(self):
    if self._records is None:
        self._records = RecordStore("alarm", self.settings,
                                    env_prefix="THALOVANT_ALARM", default_key="alarms")
    return self._records

def _load(self):                                   # at start (replaces `.load()`)
    external = self._store().load_all_with_legacy()
    if external is not None:                       # None: no database or none answered
        self.settings["alarms"] = external
    self._persisted = copy.deepcopy(self.settings.get("alarms", []))

def _save(self):                                   # replaces `.save(list)`
    after = self.settings.get("alarms", [])
    try:
        self._store().save_changes(self._persisted, after)
        self._persisted = copy.deepcopy(after)
    except RecordStoreError as error:
        LOG.warning("alarms: not saved to the database: %s", error)
        # the change stays in memory; the next save compares with the snapshot
        # taken at the last success, so it sends this change again
    self._write_settings()                          # the local fallback, as before

def _unsaved(self, owner):                         # this owner's change a save could not make
    def mine(records):
        return [r for r in records if r.get("owner") == owner]
    puts, deletes = self._store().changes(mine(self._persisted),
                                          mine(self.settings.get("alarms", [])))
    return bool(puts or deletes)

def _turn(self, owner):                            # read this owner afresh before acting
    if self._unsaved(owner):                       # an earlier save failed: send it first,
        self._save()                               # or the read below would replace it
        if self._unsaved(owner):
            return                                 # still not saved: act on what is in memory
    store = self._store()
    mine = store.load_owner(owner)
    if mine is not None:
        self.settings["alarms"] = store.splice_owner(self.settings["alarms"], owner, mine)
        self._persisted = store.splice_owner(self._persisted, owner, mine)
```

The read in `_turn` replaces both lists with what the database holds for that owner, so a
change still waiting for a save would be lost there: `_unsaved` sends it first, and while the
database still refuses it the turn works on what is in memory.
`test_a_change_an_earlier_save_could_not_make_survives_the_next_turn` runs this loop.

Keep the skill's ownership rule (the hub connection's label is the owner, never
a client-supplied name) exactly as it is: the store only trusts the `owner`
field the skill put on the record. Skills that schedule work for every owner at
start (alarms ring for everyone) call `load_all_with_legacy()` there and
`load_owner` at each turn.

In tests, `thalovant_skillkit.testing.FakeRecordStore` is the same store over
a dict: set `skill._records = FakeRecordStore("alarm")`, assert on
`store.load_all()`, count `store.backend.calls`, and rehearse a database that is
down with `store.backend.fail = OSError("down")`.

## The old document

Alarms and reminders of real people exist in the old whole-document key.
`migrate_legacy` brings them over, once:

- the old document is only read: never modified, never deleted (it is the
  rollback);
- a record is put only if it is not already there, so anything newer wins and
  a repeat does no harm;
- one pod claims the import (`SET NX` in Redis, a transaction under an advisory
  lock in PostgreSQL). A claim not finished in five minutes may be taken over,
  and the import simply repeats;
- the marker `done` is set only after a document was read and imported. A
  legacy store that was merely unreachable (`JsonStateStore.load()` answers None
  for both "no document" and "no answer") is tried again, at most every five
  minutes per process, not on every load;
- the marker is written to every backend (PostgreSQL's first) and read from all
  of them: `done` in any is done, and a backend without it is given it. A Redis
  that comes back empty after a restart has lost its marker, but PostgreSQL's
  still stops the old document from being imported again over the records
  people deleted since. If PostgreSQL cannot take the marker at the import, it is
  given it at the next check, from Redis;
- an old pod still running after the migration, and still saving whole
  documents, writes where the new code no longer reads. Roll the skills out
  together and restart the runtime pod (the kit stays in memory until then).

## Operators: running under a per-hub Redis user

A hub often gives its runtime a Redis user that may touch only the hub's own
keys (an ACL such as `~hub-<id>:*`). The store's default keys start with
`thalovant:`, which such a user is refused (`NOPERM`). The store then logs **one
warning** naming the key prefix and the ACL it needs, and the skill keeps its
records in its settings, as before. Give the store a prefix the user may touch.

**The prefix.** Set `key_prefix` in the skill's settings, or `<PREFIX>_KEY_PREFIX`
(for that skill), or `THALOVANT_RECORDS_KEY_PREFIX` (for every record skill in the
runtime; this order wins). It is one or more segments of letters, digits, `_`, `.`
and `-` joined by single colons (`hub-1:memory`), at most 200 characters. Anything
else (space, `*`, `?`, `[`, a leading, trailing or doubled colon, non-ASCII) is
refused: the store uses no Redis, says so once, and PostgreSQL still works if
configured. With no prefix the keys are exactly what 0.31.0 wrote. The PostgreSQL
table names do not change, and the old whole-document key `JsonStateStore` uses
(`thalovant:<scope>:<key>`) stays fixed: a restricted user cannot read it, so
`load()` answers None, the refusal is logged once and that process does not ask
Redis again. PostgreSQL's copy of the old document, if one is configured, is
still read (`JsonStateStore.load(redis=False)`), at most every five minutes,
until it gives a document. It only matters if you still hold records there.

**Which prefix is right.** The final keys are `<prefix>:records:v1:...`, so the
prefix must sit inside the ACL's key pattern. `hub-<id>:memory` (the journal's
own `HIVEMIND_MEMORY_KEY_PREFIX`) is inside both `~hub-<id>:*` and
`~hub-<id>:memory:*`, so it works under either ACL shape and needs nothing new
from whoever owns the user; a sibling such as `hub-<id>:skills` needs the wider
`~hub-<id>:*`. If the journal writer scans or expires everything under its own
prefix, use the sibling (and the wider ACL) instead so it never meets these keys.

**An OvosRuntime `spec.config.env` recipe.** Kubernetes expands `$(NAME)` only
for variables defined **earlier** in the same list, so these entries go after the
`HIVEMIND_MEMORY_*` ones:

```yaml
env:
  # ... HIVEMIND_MEMORY_REDIS_HOST / PORT / DB / USERNAME / PASSWORD / KEY_PREFIX first ...
  - name: THALOVANT_RECORDS_REDIS_URL
    value: redis://$(HIVEMIND_MEMORY_REDIS_USERNAME):$(HIVEMIND_MEMORY_REDIS_PASSWORD)@$(HIVEMIND_MEMORY_REDIS_HOST):$(HIVEMIND_MEMORY_REDIS_PORT)/$(HIVEMIND_MEMORY_REDIS_DB)
  - name: THALOVANT_RECORDS_KEY_PREFIX
    value: $(HIVEMIND_MEMORY_KEY_PREFIX)
```

**The password is pasted in raw.** `$(...)` does no URL escaping, so a password
containing any of `@ : / # ? %` (or a space, `+`, `&`) breaks the URL: the host is
misread and every call fails with a connection or authentication error. Either
make the password URL-safe (letters and digits) or percent-escape it and keep
the escaped copy in the Secret as a second key, then read that key:

```sh
python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" 'p@ss:w/rd+1'
# p%40ss%3Aw%2Frd%2B1
```

**What the ACL must allow.** Key pattern `~<prefix>:*` and exactly these
commands, run against a real Redis 8.2.9. The store uses no Lua, so a skill's login
needs no scripting right: Redis doesn't count a script's memory against `maxmemory`,
so a login that can load a script can take down a Redis it shares.

| Command | Used for |
|---|---|
| `MULTI`, `EXEC`, `DISCARD`, `WATCH`, `UNWATCH` | one transaction per record; a delete watches the owner's hash |
| `HSET`, `HDEL`, `HLEN`, `HEXISTS`, `HGETALL`, `HSETNX` | a record, an owner's hash, the import (put-if-absent) |
| `SADD`, `SREM`, `SMEMBERS` | the set of owners |
| `GET`, `SET` | the import marker (`SET NX EX` claims it) |
| `SELECT` | only if the URL names a database other than 0 |

`DEL`, `EXPIRE`, `SCAN`, `KEYS`, `EVAL`, `EVALSHA` and `SCRIPT LOAD` are not used. For example:

```
ACL SETUSER hub-<id> on '>PASSWORD' '~hub-<id>:*' -@all +multi +exec +discard +watch +unwatch +hset +hsetnx +hdel +hlen +hexists +hgetall +sadd +srem +smembers +get +set
```

This example is for database 0. If the URL names another database, add `+select`.

(Keep whatever the journal already needs on the same user.) `REDIS_ACL_COMMANDS`
in [records.py](../thalovant_skillkit/records.py) is this list, and
`test_a_redis_user_limited_by_an_acl_works_with_a_prefix_inside_it_and_says_no_outside`
runs the store as such a user on a live Redis.

**What a refusal looks like.** One warning, once per process, for example:
`record store alarm: Redis refused the request. This store's keys are under
'thalovant:records:v1:'. If the Redis user is limited by an ACL, it needs the key
pattern ~thalovant:* ... and the commands ...`. Read it as: the prefix is outside the
user's keys, or the user lacks a command, or the username or password is wrong. Saves
then raise `RecordStoreError` with `acl` True; reads answer None.

## Looking at a person's records

Redis (the owner key is `owner_key(label)`, from
`python -c "from thalovant_skillkit.records import owner_key; print(owner_key('<label>'))"`):

```sh
redis-cli smembers thalovant:records:v1:alarm:alarms:owners
redis-cli hgetall  thalovant:records:v1:alarm:alarms:<owner key>
```

PostgreSQL:

```sql
select id, body from thalovant_records
 where scope = 'alarm' and key = 'alarms' and owner_key = '<owner key>' order by seq;
```

## Limits

- **Last writer wins, per record.** Two pods changing the same record at the same
  moment: the later write stays. There is no version check. Two pods changing
  different records or different owners lose nothing.
- **No transaction across records.** A save of several records is one transaction
  in PostgreSQL, one transaction per record in Redis; with both backends, a failure
  of one raises `RecordStoreError` while the other has been written, and in Redis
  the records before the failure are written. Keep the snapshot of the last save
  that succeeded: the next save repeats the change.
- **Redis Cluster is not supported** (a transaction touches two keys). Redis
  with Sentinel is.
- **Order is not guaranteed** across owners in Redis; sort by your own field.
- It stores what the skill gives it: validate records, enforce ownership and keep
  the local recovery path, as with `JsonStateStore`.
