Last Edit: Claude Code (Claude Sonnet 5.5) - 2026-11-06 - Motive: Release 0.31.0: a per-owner record store for the skills that keep a person's records.

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
key (one per hub, if several share a database).

| Backend | Layout |
|---|---|
| Redis | `thalovant:records:v1:<scope>:<key>:<owner key>` is a HASH, field = the record's id, value = its JSON. `thalovant:records:v1:<scope>:<key>:owners` is a SET of the owner keys. `...:migration` is the import marker. `<scope>` and `<key>` are percent-encoded. Each change is one Lua script. |
| PostgreSQL | Table `thalovant_records (seq, scope, key, owner_key, id, body jsonb, updated_at)`, primary key `(scope, key, owner_key, id)`; `thalovant_records_meta` holds the import marker. A save's puts and deletes are one transaction. Tables are created once, under an advisory lock. |
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

def _turn(self, owner):                            # read this owner afresh before acting
    mine = self._store().load_owner(owner)
    if mine is not None:
        store = self._store()
        self.settings["alarms"] = store.splice_owner(self.settings["alarms"], owner, mine)
        self._persisted = store.splice_owner(self._persisted, owner, mine)
```

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
- an old pod still running after the migration, and still saving whole
  documents, writes where the new code no longer reads. Roll the skills out
  together and restart the runtime pod (the kit stays in memory until then).

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
  in PostgreSQL, one script per record in Redis; with both backends, a failure of
  one raises `RecordStoreError` while the other has been written. The next save
  repeats the change.
- **Redis Cluster is not supported** (a script touches two keys). Redis
  with Sentinel is.
- **Order is not guaranteed** across owners in Redis; sort by your own field.
- It stores what the skill gives it: validate records, enforce ownership and keep
  the local recovery path, as with `JsonStateStore`.
