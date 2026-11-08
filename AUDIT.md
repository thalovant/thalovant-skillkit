Last Edit: Claude Code (Claude Opus 5.5) - 2026-11-08 - Motive: The documented install pins fell behind the release (CodeRabbit on #22).
Previous:  Claude Code (Claude Opus 5.5) - 2026-11-08 - Motive: A backend that owes the import marker takes it before any save (CodeRabbit's follow-up on #52).

## 2026-11-08 the documented install pins

- Fixed (Minor, docs): [README.md](README.md) and [docs/reference.md](docs/reference.md) pinned 0.31.1 after 0.31.2 and 0.32.0 were released. Each release bumps `pyproject.toml` and `version.py`, and nothing checked the docs. Evidence: `test_the_documented_install_pins_the_version_this_is` in [test/test_packaging.py](test/test_packaging.py), which fails on 9a0f734.
- Checked, already fixed: CodeRabbit's nitpicks on #7 (one model load per `check_fleet` run: `fleet._load_model`) and #9 (the round-trip test asserts both `repo` and `sha`), both in 885a83a (#18); #22's 0.15.0 pin, in its own merge 0f3f5a3.

## 2026-11-08 the marker before any save (Unreleased)

- Fixed (Major, data integrity; CodeRabbit's reply on #52 after #58): when PostgreSQL could not take the import marker, a delete could still reach it, and if Redis then lost its data before the next check the old document came back over the delete. `RecordStore.save_changes` now gives a backend that owes the marker (`_owe_marker`, set by `_finish_migration` and `_migration_done`) the marker before anything else; until then that backend takes no save. Evidence: `test_a_delete_does_not_reach_postgres_before_its_marker`, `test_a_backend_that_could_not_be_asked_is_given_the_marker_before_a_save`, both failing on 891e33f.
- Remaining (the general limit, unchanged): a delete PostgreSQL did not take, because it owed the marker or was down, exists only in Redis. If Redis then loses its data, PostgreSQL's copy brings the record back, as with any save one backend failed; the skill's retry closes this while the process lives. The debt itself is kept in memory, and after a restart the start-up check (`load_all_with_legacy`) finds it again.

## 2026-11-07 the open CodeRabbit findings (Unreleased)

- Fixed (Major, data integrity): a deleted record came back after Redis lost its data, because the import marker was only in Redis and the old document was imported again into both backends. [records.py](thalovant_skillkit/records.py) `RecordStore._migration_done`, `RecordStore._finish_migration`, `PostgresBackend.migration_finish` (now an upsert). Evidence: `test_a_redis_that_lost_its_data_does_not_bring_back_a_deleted_record` (fakeredis with sqlite, and live Redis 8.2.9 with PostgreSQL 17), `test_a_marker_postgres_could_not_take_is_given_at_the_next_check`, `test_the_marker_is_set_without_holding_the_claim`, `test_a_done_marker_in_any_backend_is_enough`. All fail on `main`.
- Fixed (Major, availability): when Redis refused the old key, a PostgreSQL failure at the same moment kept the old records out until a restart. `RecordStore.migrate_legacy` now reads only PostgreSQL after a refusal (`JsonStateStore.load(redis=False)`). Evidence: `test_after_a_refusal_postgres_is_still_read_until_it_answers`.
- Fixed (Major, availability): `JsonStateStore` turned PostgreSQL off for good after one failed connect, and kept a connection PostgreSQL had closed. [storage.py](thalovant_skillkit/storage.py) `_postgres` (`POSTGRES_RETRY_SECONDS`), `_drop_postgres`. Evidence: `test_a_postgres_that_could_not_be_reached_is_tried_again_after_a_while`, `test_a_connection_postgres_closed_is_replaced_on_the_next_call` in [test/test_storage.py](test/test_storage.py).
- Fixed (docs): [docs/records.md](docs/records.md)'s example raised `AttributeError` on `self._records` and lost a change at the next turn after a failed save (`test_a_change_an_earlier_save_could_not_make_survives_the_next_turn` runs the corrected loop). The 0.31.0 CHANGELOG entry overstated a failed save.
- Accepted: if Redis loses its data and PostgreSQL cannot answer the marker check at the same moment, the import runs into Redis as it did before. A PostgreSQL that is down at the first start must not hold up people's records (`test_a_mirror_that_cannot_answer_does_not_hold_up_the_import_into_the_first`).
- Accepted: while PostgreSQL is down, `JsonStateStore` tries a connect (one-second timeout) and logs one warning at most every 60 s, where before it gave up after the first.
- Open (Minor, unchanged): last writer wins per record; there is no transaction across records.

## 2026-11-07 the service token (Unreleased)

- Added: the runtime group's token is sent as `Authorization: Bearer` by [service_auth.py](thalovant_skillkit/service_auth.py) (`with_service_token`, `is_service_url`), only to `SERVICE_HOSTS` (seven services, namespace `thalovant`, three name forms). Evidence: [test/test_service_auth.py](test/test_service_auth.py), 184 passed.
- Guarded (owner-editable URLs): local-pulse sends request headers to feeds its owner configures, and every `service_url` can be edited, so the token is never attached by host suffix or by service name alone; a bare `thalovant-llm` is refused because it falls through the pod's DNS search list. `test_no_other_host_is`, `test_request_headers_never_carry_it_elsewhere`, `test_post_json_never_sends_it_elsewhere`, `test_ask_service_to_an_owner_set_url_sends_no_token`.
- Guarded (redirects): urllib copies ordinary headers onto any redirect; `JsonServiceClient._send` uses `add_unredirected_header`. `requests` drops `Authorization` across hosts by itself. `test_json_client_redirected_elsewhere_does_not_take_the_token_along`, `test_a_service_redirecting_elsewhere_does_not_take_the_token_along`, `test_ask_service_redirected_elsewhere_does_not_take_the_token_along`.
- Accepted: any code in the runtime can read the token file and send it anywhere; the helpers only make the shared paths safe. Skills calling a service with their own `requests` call send nothing until they pass `url=` (coming-soon, joke-garden, learning-lounge's joke call, local-pulse, on-this-day, pop-facts, pop-quiz, weather, what-next).
- Accepted: a 401 is repeated once when the token changed, including from `JsonServiceClient`, whose POSTs are otherwise never repeated; a 401 is a refusal before the request is handled.
- Not exercised: a real mounted Secret in a pod (the symlink layout is reproduced in `test_the_kubelets_symlink_swap_is_seen`).

## 2026-11-06 — RecordStore needed Lua, which could take down a shared Redis

An independent review ran `SCRIPT LOAD` and `EVALSHA` with a runtime login's rights on Redis 8.2.9 and built a string past the container's memory limit from Lua. Redis was OOM-killed (`oom=true exit=137`). Lua memory isn't limited by `maxmemory`. RecordStore was the only reason a runtime login needed those rights. `RedisBackend` in `thalovant_skillkit/records.py` now uses `MULTI` and `WATCH`, tested by `test_the_redis_backend_never_uses_a_script` and `test_a_write_during_a_delete_keeps_the_owner` in `test/test_records.py`. The login's rights are removed in hivemind-k8s-operator.

# Audit

## 2026-11-06 key prefix and a Redis that refuses (0.31.1)

- Fixed (Major, silent fallback): a runtime whose Redis user is limited to `~hub-<id>:*` was refused every `RecordStore` key (`thalovant:records:v1:...`, `NOPERM`) and fell back to the skill's settings without a clear sign. The prefix is now configurable ([records.py](thalovant_skillkit/records.py) `RecordStore.__init__`, `RedisBackend`, `valid_key_prefix`) and a refusal is one warning naming the prefix and the ACL (`RecordStore._failed`, `REDIS_ACL_COMMANDS`). Evidence: `test_every_redis_key_goes_under_the_prefix`, `test_a_refusal_by_redis_is_logged_once_with_the_prefix_and_the_commands`, `test_a_redis_user_limited_by_an_acl_works_with_a_prefix_inside_it_and_says_no_outside` (real Redis 7, a user with `~hub-1:*` and only the listed commands, a password of `@ : / + # ? %`), 123 tests, none skipped with live Redis 7 and PostgreSQL 16.
- Found: the operator recipe named `THALOVANT_RECORDS_REDIS_URL`, which nothing read; it now does (`RecordStore.__init__`).
- Open (Minor): `JsonStateStore` keeps its fixed `thalovant:<scope>:<key>` key; a restricted user cannot read it, so `migrate_legacy` sees "no document" and retries at most every five minutes. Skills that still use `JsonStateStore` stay refused under such a user.
- Open (Minor, operator): a prefix inside the journal's own (`hub-<id>:memory`) is only safe if the journal writer does not scan or expire everything beneath it; use a sibling prefix and `~hub-<id>:*` otherwise. A password with URL-special characters pasted by `$(VAR)` breaks the URL (documented).

## 2026-11-06 per-owner records (0.31.0)

- Fixed (Major, data loss): `JsonStateStore` rewrites every owner's records as one document on each save: two owners or two hub pods saving together lose one change ([storage.py](thalovant_skillkit/storage.py) `save`, `_save_redis`). `RecordStore` ([records.py](thalovant_skillkit/records.py)) replaces it for skills that keep a person's records: one write per changed record, by (owner, id). Evidence: `test_a_pod_with_a_stale_copy_does_not_overwrite_the_others`, `test_twenty_threads_over_two_pods_lose_nothing` on memory, fakeredis, the SQL over sqlite, and a real Redis 7.4 and PostgreSQL 16.15 (all passing, three runs).
- Open (Major, until the skills move): alarm, reminder, timer and stopwatch still use `JsonStateStore`; the fix reaches users only when each releases a version that swaps to `save_changes` and `load_all_with_legacy`, and the hub restarts its runtime pod (the kit stays in memory).
- Known limits: last writer wins for one record changed by two pods at once (no version check); no transaction across records (a save is one transaction in PostgreSQL and one script per record in Redis, so with both backends one can succeed while the other fails: `RecordStoreError`, the next save repeats it); Redis Cluster is not supported (scripts touch two keys); a Redis refill from PostgreSQL copies only records that are absent.
- Open (Minor, legacy): the old whole document is never deleted, so an old pod still saving whole documents after the migration writes where the new code no longer reads. `JsonStateStore.load()` answers None both for no document and no answer, so the migration is retried (at most every five minutes) until a document is read.
- Not exercised: Redis behind Sentinel, a PostgreSQL that drops the connection mid-save (the connection is dropped and made again on the next call; covered by `test_a_backend_that_is_down_raises_on_save_and_reads_as_none` only through an injected failure).

## 2026-11-05 the floor, the lock and the review's open notes (0.30.0)

- Fixed (Major, security): thirteen Dependabot alerts on `filelock` 3.32.7 in `uv.lock` (GHSA-v4x8-3wr5-3wq8 high; eleven medium; one low), all patched in 4.2.1 or earlier, all `requires-python >=3.11`. The floor is 3.11 and the lock overrides combo-lock 0.3.1's `filelock~=3.0` to take 4.2.9. Evidence: a dry-run lock on `>=3.11` without the override kept 3.32.7; combo-lock's own suite (0.3.1 sdist) gives the same result on 3.32.7 and 4.2.9 (`tests/test_lock.py::test_lock_file_missing` and `::test_process_lock` fail on both for harness reasons, ten pass); the kit's 703 tests pass on 3.11 and 3.13 with `filelock.__version__ == "4.2.9"`. Exposure that remains: a `pip install thalovant-skillkit` (the hub, CI's own jobs) still resolves 3.x through combo-lock; of the thirteen, GHSA-69hj-f68j-2879 (`UnixFileLock` truncating a file renamed onto the lock path by another local user) is the one on the class combo-lock uses, with the lock files at mode 0o666 in a shared RAM directory. The fix for that is upstream (forslund/combo-lock#28).
- Fixed (Minor): `handle_fallback` spoke with `self.speak(text)`; it now answers the message it was given through `speak_to`. Evidence: `test_reply_is_spoken_on_the_hub_and_returned_to_the_showroom` with the double capturing `speak_to`; `test_the_fallback_reply_carries_the_twin` on the live bus unchanged.
- Fixed (records): `fold_tight`'s docstring; `Action.as_dict`, `Item.as_dict`, `Clear.as_dict` docstrings; the README's "SkillKit itself supports Python 3.10"; the reference's fallback paragraph; the 0.29.0 integration matrix comment that called 3.10 the kit's floor.
- Fixed (test): `test_the_layout_is_found_in_the_directory_of_the_skills_own_module` plants a layout beside a module loaded under `sys.modules` and reads it with neither `root=` nor `root_dir`, the positive case 2026-11-04 asked for.
- Checked and kept: `tokenizers<1` (model2vec 0.10.0 `model.py:67` calls `get_vocab()`; tokenizers 1.0.0rc3 is the newest 1.x); `SkillResources.dialog` catching `KeyError`/`IndexError` only, which the reference states; `display.showing` thread-local, as recorded.
- Open: combo-lock's requirement upstream. Until it is widened, the override in `pyproject.toml` must stay, and a reader of the lock should know the hub does not get the same filelock.

## 2026-11-05 whole-kit review (0.29.2)

Every module under `thalovant_skillkit/` was read, with the CodeRabbit threads on #19 to #49.

- Fixed (Minor, #47 outside the diff): `display.layout` accepted non-finite floats in `data`; `display.layout` took a non-bytes `image` to a `TypeError`; `display.tap` and `display._figure` raised `OverflowError` on an integer too large for a float. Evidence: reproduced on 0.29.1 (`tap({... "at": 10**400})`, `layout(data={"t": nan})`, `layout(image=("a path", "image/png"))`, `weather(temperature=10**400)`). Tests: the nine new cases of `test_what_the_satellite_would_not_show_fails_here` and the two in `test_a_tap_on_this_skills_card_reaches_the_handler`.
- Fixed (Major): `knowledge.ask_service` handed a non-object body to `knowledge_reply`, which raised `AttributeError` and failed the turn. Evidence: reproduced with a fake `requests.post` returning a list, a string and an integer, with and without a notice. Test: `test_a_body_that_is_not_a_document_is_a_failed_request_on_both_paths`.
- Fixed (test): `test_real_core_sends_a_twin_with_the_fallback_reply` depended on OVOScope's default pipeline, which omits the low fallback band when adapt and padatious are installed. Evidence: a probe of the captured turn showed `ovos.intent.unmatched` with the pipeline list ending at `ovos-fallback-pipeline-plugin-medium`. The test names `FALLBACK_PIPELINE`.
- Fixed (records): README quickstart at 0.22.0; reference without `moments`, the lookup notice, `speak_to(display=)` and `layout(fullscreen=)`, `[testing]` at 0.12.0; `check` notes naming the empty `[fleet]` extra; `publish.yml` artifact actions by floating tag; the certifi bump missing from the 0.29.0 changelog (#48, the one CodeRabbit thread still open).
- Open (closed in 0.30.0, above): Dependabot's security update for `filelock` fails on `main` because the patched versions need Python 3.11 and `requires-python` is `>=3.10`; raising the floor is the owner's call. `handle_fallback` speaks with `self.speak(text)` rather than `speak_to(message, ...)`; OVOS resolves the session's language from the handler's stack, so it answers the room that asked, but a skill answering from another thread should call `speak_to`. `fold_tight` keeps ASCII letters and digits only, which its docstring ("letters and digits") understates for a non-Latin identifier. `display.showing` is thread-local, as recorded on 2026-11-04. `SkillResources.dialog` catches `KeyError`/`IndexError` and not `ValueError`, as the reference says. None of these changed behaviour here.
- Checked and sound: `text.py` (the kept-marks table and `WORD_CHAR`), `vocab.py`, `locale.py`, `message.py`, `fallback.py`, `service.py`, `bus.py`, `sessions.py`, `selection.py`, `network.py`, `workers.py`, `storage.py`, `regions.py`, `intents.py`, `fleet.py`, `checks.py`, `ssml.py`, `artifacts.py`, `moments.py`, `speech.py`, `cli.py`'s scaffold against the docs' "Writing a Skill" page, and the kit's display limits against thalovant-voice `src/thalovant_voice/display.py` on `main` (identical constants; the satellite drops a `lang` that is not a tag rather than refusing the card).

## 2026-11-04 review follow-up on #47

- Fixed: `_skill_root` in `thalovant_skillkit/display.py` resolved a class argument through its metaclass. Evidence: CI run 41912545035 failed `test/test_display.py::test_the_layout_is_read_beside_the_skills_module` on 3.10, 3.12 and 3.14 (the C `_abc` metaclass has no source file, `inspect.getfile` raised `TypeError`, and `CardError("cannot find the skill's directory")` came out instead of "not found"); locally the test passed only because the `abc` module's directory holds no layout. The class is now resolved when a class is passed.
- Fixed: the module docstring's two examples called `speak_dialog` / `speak` with `display=`, which those OVOS-signature methods do not accept.
- Open: `test_the_layout_is_read_beside_the_skills_module` asserts the failure text, not the directory searched; a test that plants a layout beside the fixture skill and reads it would prove the lookup positively.


## 2026-11-04 display cards

- `display.showing` keeps the pending card in a thread-local; a handler that speaks from another thread it started (a worker) does not see it, and must pass `display=` to `speak_to` instead. Evidence: `test/test_display.py::test_a_showing_block_attaches_the_card_to_every_reply_inside` runs on one thread.
- `layout_file` reads the file on every call; a skill answering often should keep the `Layout` it returns. The sent-once set (`_sent_layouts`) was removed in 0.29.1: it was per process, not per satellite, so only the first satellite to ask got the text (the Mark II, 2026-11-05).
- A tap report is believed by its `skill` field or a `card` id prefixed with this skill's id; a hub that let another connection forge the field would reach the handler, which is why `tap` carries no more than ids and a time and the handler must answer only with what the skill would say to anyone.

## 2026-11-03 moments rule fallbacks (review follow-up from #30)

- Fixed (Minor): `_time_by_rule` in [thalovant_skillkit/moments.py](thalovant_skillkit/moments.py)
  used the locale's short clock whenever a rule set had no pattern for the requested cycle. On
  `main`, `time_text(22:18, "en-US", use_24hour=True, written=True, rules={"am": "a.m.", "pm": "p.m."})`
  returned `"10:18 p.m."`, and the French 12-hour equivalent returned `"22:18"`. Both now honour
  `use_24hour`. Tests:
  - `test_marker_only_rules_keep_the_asked_for_24_hour_clock`
  - `test_marker_only_rules_keep_the_asked_for_12_hour_clock`
  - `test_marker_only_rules_keep_the_locale_marker_placement`
  - `test_a_quoted_letter_is_not_an_hour_field`
- Fixed (Major): `date_text` applied the rule branch before the near-day check, so with rules a
  reminder due today was written as `"Thursday, August 27, 2026"` instead of `"today"`,
  contradicting its docstring. Only today and tomorrow skip the rules now; yesterday keeps its
  rule-written date. Tests:
  - `test_date_rules_keep_today_and_tomorrow`
  - `test_date_rules_still_write_yesterday`
  - `test_date_rules_apply_to_a_near_day_when_relative_is_refused`
- Exposure: none in released skills today. The only caller that passes rules, the date-time
  skill, ships both time patterns in every locale and writes dates with `relative=False`.
- Evidence: ruff clean. Python 3.10: 627 passed, 32 skipped. Python 3.14: 631 passed, 28 skipped.
  The date-time suite passes against the branch.
