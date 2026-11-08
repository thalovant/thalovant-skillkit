Last Edit: Claude Code (Claude Opus 5.5) - 2026-11-07 - Motive: Send the runtime group's service token to the platform's services only (service_auth).
Previous:  Claude Code (Claude Opus 5.5) - 2026-11-06 - Motive: Release 0.32.0: RecordStore uses no Lua.
## 2026-11-07 — the service token, to the platform's services only (Unreleased)

`thalovant_skillkit/service_auth.py` (`ServiceToken`, `is_service_url`, `with_service_token`, `retry_headers`, `SERVICE_HOSTS`) reads the token file named by `THALOVANT_SERVICE_TOKEN_FILE`, cached by its stat, and decides per URL whether the token may go. Wired into `request_headers(..., url=)` and `post_json` (`service.py`), `JsonServiceClient.post` (`network.py`, as an unredirected header) and `ask_service` with its streamed reader (`knowledge.py`, `_post`). No version bump: the release is cut separately.

Verification: `test/test_service_auth.py`, 184 cases: each service and host form allowed; 27 external, look-alike, userinfo, backslash, fragment, bare-name, address and malformed URLs refused through every helper; headers built for a service stripped on the way elsewhere; redirects (301/302/303/307/308 through `requests`, 301/302/303 through urllib's own handlers) never carry it off the host; the kubelet's `..data` symlink swap picked up; 401 retried once only with a new token; missing or malformed file sends nothing and logs no token. Eight mutations (ordinary urllib header, no strip, always retry, bare names allowed, userinfo allowed, `ask_service` unwired, no retry, no stat check) each fail 3 to 46 cases. Full suite: 967 passed, 64 skipped (Python 3.12); ruff clean.

Transparency Report. AI Model: Claude Opus 5.5 (`claude-opus-5-5`) in Claude Code. Actions Taken: wrote `service_auth.py`, wired it into the four helpers, wrote the tests and the mutations, updated the reference, CHANGELOG and AUDIT. Oversight: requested by the owner's lead agent for stage 1 of shared-service authentication; no human review before the PR.

## 2026-11-06 — 0.32.0: RecordStore without Lua

`RedisBackend` writes through transactions instead of Lua, because a login that can load a script can take down a shared Redis. Behaviour is unchanged: an owner still leaves the set with their last record, and `WATCH` covers the race the script closed. Redis Cluster stays unsupported.

Verification: `test/test_records.py` on fakeredis and on a real Redis 8.2.9, including as a user limited to `REDIS_ACL_COMMANDS`; results are in the pull request.

Transparency Report. AI Model: Claude Opus 5.5. Actions Taken: rewrote the Redis writes and their tests, updated the docs. Oversight: requested by the owner ("make sure all is perfect"), after an independent review found the crash; no human review before merge.

# Maintenance report

## 2026-11-06 - 0.31.2: the shared Redis URL switches RecordStore on

`RecordStore.__init__` set `self._config.redis_url` from `THALOVANT_RECORDS_REDIS_URL` after `JsonStateStore` had computed `enabled`, so `RecordStore.enabled` stayed False and the timer, reminder and stopwatch skills returned early. The store now sets `enabled`. `test/test_records.py::test_the_shared_redis_url_alone_switches_the_store_on` failed before the fix.

The legacy import no longer retries after Redis refuses the read (`JsonStateStore.redis_refused`), which would otherwise warn every five minutes for ever under a limited user. Verified on real Redis 7 under the hub ACL rules with environment variables only, through `enabled`, `load_all_with_legacy` and `save_changes` for all four record skills, with a second store instance reading the records back; with the first fix removed the same run fails.

### Transparency report

AI model Claude Opus 5.5 (`claude-opus-5-5`) in Claude Code made the change, the tests and this entry. No human review before the PR.

## 2026-11-06: a key prefix and a one-time ACL warning (0.31.1)

- **Found:** the coordinator's finding that Daily Desk's runtime gets a per-hub Redis user (`HIVEMIND_MEMORY_REDIS_*`, prefix `hub-<id>:memory`), probably ACL-limited to `hub-<id>:`; `RecordStore`'s fixed `thalovant:` keys would be refused (`NOPERM`) and the skill would fall back quietly. Reproduced on a real Redis 7 with a user restricted to `~hub-1:*`: `NoPermissionError` on the first key outside the prefix. Removing each command in turn from the allowed list, with the script cache flushed, showed every command in `REDIS_ACL_COMMANDS` is needed (`SELECT` only for a database other than 0). `THALOVANT_RECORDS_REDIS_URL`, used in the proposed recipe, was read by nothing.
- **Changed:** `thalovant_skillkit/records.py` (`key_prefix` setting and environment, `valid_key_prefix`, `RedisBackend(prefix=)`, `REDIS_ACL_COMMANDS`, `RecordStoreError.acl`, one warning per process for an ACL refusal, `THALOVANT_RECORDS_REDIS_URL`); `test/test_records.py` (prefix keys, owner set, marker, precedence, good and bad prefixes, two prefixes on one Redis, the once-only warning, a live ACL-limited user); `docs/records.md` (operator section); CHANGELOG; AUDIT; version 0.31.1 (`pyproject.toml`, `version.py`, README and reference pins, the root package line of `uv.lock` only).
- **Not done here:** `JsonStateStore` keeps its fixed key (a prefix would orphan existing documents); the skills and the OvosRuntime manifests are not changed (the hub's env entries are the owner's to add); nothing was run against the real Daily Desk Redis or its ACL.
- **Transparency Report:** AI model Claude Sonnet 5.5 (`claude-sonnet-5-5`) in Claude Code made the changes, wrote the tests and these entries, and ran the suite and the ACL probes against Redis 7 and PostgreSQL 16 containers. No human review before the pull request.

## 2026-11-06: a per-owner record store (0.31.0)

- **Found:** the lists skill's worker showed the weakness every record-keeping skill shares: `JsonStateStore` keeps all owners' records as one document under one key and rewrites it whole on each save, so two owners or two hub pods saving together overwrite each other (a lost update) and a pod's copy, read once, goes stale. The alarm, reminder, timer and stopwatch skills all stand on it. The lists skill's own store (a hash per owner, Lua scripts, rows with advisory locks) was the working design.
- **Changed:** new `thalovant_skillkit/records.py` (`RecordStore`, `RedisBackend`, `PostgresBackend`, `MemoryBackend`, `owner_key`, `RecordStoreError`, `Changes`) configured exactly like `JsonStateStore` (same settings, environment and key), per-record atomic writes by (owner, id) from a before/after diff, owners hashed into every key, a once-only and non-destructive import of the old whole document; `testing.FakeRecordStore`; `docs/records.md`; the reference section; version 0.31.0 (0.30.0 was already released on 2026-11-05, so this is not it). `.github/workflows/test.yml` installs fakeredis, lupa, redis and psycopg and starts Redis 7 and PostgreSQL 16 for the `test` job so the live suite runs on every pull request.
- **Verification:** `ruff check thalovant_skillkit test scripts` clean; the whole suite passes; `test/test_records.py` runs the same operations on memory, fakeredis (real Lua) and the real SQL over a sqlite adapter, and, against a real Redis 7.4 and PostgreSQL 16.15 in containers, ran three times in a row without a failure, including 20 threads over two stores, the tricky owner labels, eight pods migrating at once, a claim taken over, and a Redis refilled from PostgreSQL.
- **Not done here:** the skills (alarm, reminder, timer, stopwatch) are not changed in this release; each swaps `_state_store().save()` for `save_changes(before, after)` using `docs/records.md` and calls `load_all_with_legacy()` at start. Until then they keep the old whole-document behaviour. Nothing was run against Redis Cluster (not supported) or a Sentinel.
- **Transparency Report:** AI model Claude Sonnet 5.5 (`claude-sonnet-5-5`) in Claude Code designed on the lists skill's store, wrote the module, tests, docs and this entry, and ran the suite against containers. No human review before the pull request.

## 2026-11-05: Python 3.11 floor, filelock 4.2.x, the fallback through speak_to (0.30.0)

- **Found, the thirteen open Dependabot alerts (one high):** all on `filelock` 3.32.7 in `uv.lock`, all fixed in 4.2.1 (one in 4.0.9), every patched version `requires-python >=3.11`. Raising the kit's floor alone changed nothing: a dry-run lock on `>=3.11` kept 3.32.7, because combo-lock 0.3.1 (ovos-utils, ovos-config, ovos-core, ovos-plugin-manager and json-database depend on it) requires `filelock~=3.0`. combo-lock uses `FileLock(path, mode=)`, `acquire(timeout=)` and `Timeout`, all kept in 4.x; its own test suite from the 0.3.1 sdist gives the same two harness failures (`tests/process.py` is not in the sdist) and ten passes on 3.32.7 and on 4.2.9. Upstream already has the ask (forslund/combo-lock#28, 2026-10-29, no PR yet).
- **Found, the review's open notes:** `handle_fallback` spoke with `self.speak(text)` while `speak_to`'s own docstring calls that wrong for a reply from another thread or on a hub answering two rooms; `fold_tight`'s docstring said "letters and digits" for an ASCII-only fold; three `as_dict` methods had no docstring (CodeRabbit's docstring check); `test_the_layout_is_read_beside_the_skills_module` proved only the failure text. The `tokenizers<1` pin was checked against model2vec 0.10.0's wheel: `model.py:67` still calls `get_vocab()`, and tokenizers 1.0.0 is at rc3 (2026-10-19), so it stays.
- **Changed:** `pyproject.toml` (0.30.0; `requires-python >=3.11`; classifiers 3.11 to 3.14; `tomli` dropped; the tokenizers comment names rc3 and model2vec 0.10.0's call; `[tool.uv] override-dependencies = ["filelock>=4.2.1"]` with the reason and the condition for removing it); `thalovant_skillkit/version.py`; `checks.py` (plain `import tomllib`); `skill.py` (`handle_fallback` calls `self.speak_to(message, text)`); `text.py` (`fold_tight` docstring); `display.py` (three docstrings); `scripts/check-installed-package.py` (the 3.11 guard ruff now calls outdated); `.github/workflows/test.yml` (3.11, 3.12, 3.14; integration 3.11 and 3.14); `test/test_skill_base.py` (`_Spoken` captures `speak_to`); `test/test_display.py` (`test_the_layout_is_found_in_the_directory_of_the_skills_own_module`); `test/fixtures/thalovant-skill-punchline/pyproject.toml` (`>=3.11`); README (the floor, the 0.30.0 pin); `docs/reference.md` (the fallback paragraph, the `[testing]` pin); CHANGELOG; `uv.lock` (`uv lock --upgrade --prerelease=allow`: filelock 4.2.9 under the override, tomli and exceptiongroup gone, the project at 0.30.0).
- **Verification:** `ruff check thalovant_skillkit test scripts` clean; `uv run --frozen python -m pytest -q`: 703 passed on Python 3.13, and 703 passed on Python 3.11 (`uv run --python 3.11 --all-extras`), both with filelock 4.2.9 imported from the lock. CI on the PR is the proof for 3.12 and 3.14, the installed wheel and the OVOS integration job (which installs with pip and therefore still gets filelock 3.x).
- **Not done here:** the upstream widening of combo-lock's requirement (forslund/combo-lock#28) is the fix that reaches a `pip install`; a PR there is the owner's to open under their name. CodeRabbit's docstring-coverage check passed on #50 (81.82%) and is not configured in this repository (no `.coderabbit.yaml`).
- **Transparency Report:** AI model Claude Fable 5.1 (`claude-fable-5-1`) in Claude Code made the changes, ran combo-lock's suite on both filelock lines, and wrote these entries. No human review before the PR.

## 2026-11-05: review follow-ups and a knowledge body that is not a document (0.29.2)

- **Found, CodeRabbit on #47 (four "outside the diff" findings, never answered) and #48 (one, unresolved):** `display.layout(data=...)` accepted `NaN`/infinity (`json.dumps` default `allow_nan=True`); a layout's `image` was not checked to be bytes, so a path raised `TypeError`; `tap()` ran `math.isfinite` on a raw `int`, so an `at` of `10**400` raised `OverflowError` out of the bus handler; and the 0.29.0 changelog left out the certifi bump (#45). The fourth 0.29.0 finding (a layout marked sent during serialization) was moot after 0.29.1 removed the sent set. Reproduced each on 0.29.1 with the installed package before changing anything; `_figure` had the same overflow (`weather(temperature=10**400)`, `item("x", 10**400)`).
- **Found, reading `knowledge.py`:** `ask_service` returned `response.json()` unchecked on the plain path and on a streamed reply that was not NDJSON; a list or a string reached `knowledge_reply`, which raised `AttributeError` on `.get` and failed the turn, while the streamed path had refused the same shape since 0.27.0. Reproduced with a fake `requests.post`.
- **Found, running the suite from the checkout:** `test_real_core_sends_a_twin_with_the_fallback_reply` failed locally (`uv run --frozen`) and passed in CI. `uv.lock` was six weeks behind the prereleases CI installs (ovoscope 1.9.0a1 against 1.12.1a1), but a refreshed lock still failed: OVOScope picks its `LEAN_DEFAULT_PIPELINE` when the adapt and padatious plugins are installed, and that pipeline has no `ovos-fallback-pipeline-plugin-low`, so a skill at priority 97 was never asked (`ovos.intent.unmatched`). CI's pip install lacks padatious and falls back to a pipeline with the band. The test now names `FALLBACK_PIPELINE`, as the docs' own MiniCroft example does.
- **Found, reading the records:** the README's quickstart pinned 0.22.0 (seven releases back); the reference's `[testing]` pin said 0.12.0, its `speak_to` signature lacked `display=`, and it never mentioned `moments` (0.19), the lookup notice and `ask_service` (0.26 to 0.28) or `layout(fullscreen=)`; `fleet.check_fleet` told a user to install the `[fleet]` extra, empty since the base install took model2vec; `publish.yml` used `upload-artifact@v4` and `download-artifact@v4` by floating tag in a workflow whose every other step is pinned by commit.
- **Changed:** `display.py` (`_figure`, `_image` shared by `media` and `layout`, `layout` with `allow_nan=False`, `tap` converting `at` inside a `try`); `knowledge.py` (`_document` on both plain paths); `fleet.py` (the two notes); `__init__.py` docstring (the modules it left out); `test/test_display.py` (nine refusals and two tap cases), `test/test_knowledge_notice.py` (one parametrized test over both paths), `test/test_testing_ovos.py` (the pipeline); README quickstart and two sections (`moments`, the lookup notice); `docs/reference.md` (a "Dates and clocks" section, a "Saying where a slow answer comes from" subsection, the display and `speak_to` additions, the `[testing]` pin); CHANGELOG (0.29.2, and the certifi line under 0.29.0); `pyproject.toml` (0.29.2; the model2vec comment now says 0.10.0 keeps the open `tokenizers` range, so the `<1` pin stays); `publish.yml` (both artifact actions pinned to the commits `v4` points at: upload 4.6.2, download 4.3.0); `uv.lock` (`uv lock --upgrade --prerelease=allow`: ovoscope 1.12.1a1, ovos-workshop 9.10.1a1, ovos-core 3.7.5a1, ovos-config 3.9.0a2, model2vec 0.10.0, certifi 2026.10.23; filelock stays 3.32.7 because every patched 4.x needs Python 3.11 and the kit's floor is 3.10, which is why Dependabot's security update for it fails on `main`).
- **Verification:** `ruff check thalovant_skillkit test scripts` clean; `uv run --frozen python -m pytest -q`: 702 passed on Python 3.13 from the refreshed lock, including the 27 of `test/test_testing_ovos.py`; the four display edge cases and the three knowledge bodies reproduced on 0.29.1 and refused on this branch. CI on the PR is the proof for 3.10, 3.12 and 3.14 and for the installed wheel.
- **Not done here:** the Python 3.10 floor (which blocks filelock 4.x and keeps Dependabot's security job red) is a decision for the owner: CI's matrix calls 3.10 "the oldest a skill may run on". The `tokenizers<1` pin is kept until model2vec declares an upper bound or is seen to work with 1.x. CodeRabbit's "docstring coverage" pre-merge check on #47 was not chased.
- **Transparency Report:** AI model Claude Fable 5.1 (`claude-fable-5-1`) in Claude Code reviewed every module, the CodeRabbit threads on #19 to #49, and wrote the changes, the tests and these entries. No human review before the PR.

## 2026-11-05: a layout's text travels with every card (0.29.1)

- **Found:** the Mark II logged `display: showing text card weather (layout_missing)` after the weather skill 0.5.0 was installed on Daily Desk. The hub's `display._sent_layouts` is a process-wide set: the first card with a layout hash carried the text, every later card for any satellite carried only the hash. A monitoring client asking the weather every five minutes took the inline copy.
- **Changed:** `Card.as_dict` always sends `rfw`; the set and its lock are gone; `forget_sent_layouts` is a no-op. `test_a_layout_travels_inline_with_every_card` replaces the once-then-hash test.
- **Verification:** 663 passed, 28 skipped.
- **Transparency Report:** AI model Claude Sonnet 5.5 (`claude-sonnet-5-5`) in Claude Code wrote the change from the satellite's and the hub's logs. No human review before the PR.

## 2026-11-04 review follow-up on #47 (CodeRabbit, three findings)

- `_skill_root` (`thalovant_skillkit/display.py`): a skill passed as a class was resolved through `type(skill)`, the metaclass (`abc.ABCMeta` under OVOS's `FallbackSkill`), never the module that defines it. Locally the `abc` module's directory holds no layout, so `test_the_layout_is_read_beside_the_skills_module` passed by accident; on CI (3.10, 3.12, 3.14) the C-implemented metaclass has no file, `inspect.getfile` raised and the test saw "cannot find the skill's directory" instead of "not found". The class itself is now resolved (`klass = skill if isinstance(skill, type) else type(skill)`); instances keep the old lookup.
- The module docstring's examples passed `display=` to `speak_dialog` and `speak`, which keep the OVOS signatures and would raise `TypeError`; they now use `display.showing(card)` and `speak_to(message, ..., display=...)`, as the README does.
- The entry below had 26 tests, a green suite and a stale 0.18.0 remark; corrected.
- **Verification:** `test/test_display.py` 32 passed, the whole suite 691 passed with `[testing]`, `ruff check` clean; CI on the push is the proof for 3.10/3.12/3.14.
- **Transparency Report:** AI model Claude Fable 5.1 (`claude-fable-5-1`) in Claude Code applied the three fixes and resolved the threads. No human review before the push.


## 2026-11-04 display cards for a satellite with a screen

- **Contents:** `thalovant_skillkit/display.py` (new): builders for the card a satellite with a display draws from `meta["display"]` -- `text`, `list_card`, `weather`, `media`, `layout` with `layout_file` reading `gui/thalovant/<name>.rfwtxt` -- `action`, `item`, `clear`, `attach`, the `showing` context manager and `pending`, and `tap` for the `thalovant.display.action` report. `skill.py`: `speak` and `speak_dialog` attach a pending card (their OVOS signatures unchanged, as `test_the_speech_overrides_keep_the_framework_signatures` requires); `speak_to` and `speak_varied_dialog` take `display=`; `_SkillPlumbing.add_display_action_handler` follows the tap event once and delivers `Tap`s for this skill's cards.
- **Sizes:** the satellite's own bounds (thalovant-voice `display.py`) are mirrored as constants and checked when a card is built, so a card that will not be shown raises `CardError` here with the reason. A layout's text travels inline once per process and by `sha256` afterwards.
- **Verification:** `ruff check` clean on the three files; `test/test_display.py` (new, 32 tests: the size-refusal test counts 20 cases) and the whole suite: 691 passed with `[testing]` on this machine. CI on #47 failed `test_the_layout_is_read_beside_the_skills_module` on 3.10, 3.12 and 3.14 until the `_skill_root` fix in the entry above.
- **Not done here:** no skill uses it yet (the weather skill's card is its own change); the control-plane grant for `thalovant.display.action` is thalovant-api's. The guide skill's credits card (thalovant-skill-guide #63) is the first user.
- **Transparency Report:** AI model Claude Fable 5.1 (`claude-fable-5-1`) in Claude Code wrote the module, the plumbing, the tests and these entries. No human review before the PR.

## 2026-11-03 moments: written rules keep the asked-for clock and the relative day

Two review findings on #30, both still present on `main`, are fixed in
[thalovant_skillkit/moments.py](thalovant_skillkit/moments.py):

- `_time_by_rule`: a rule set with no `time_pattern` / `time_pattern_24` fell back to Babel's
  `"short"`, the locale's own cycle, which could overrule `use_24hour`. The new
  `_cldr_clock_pattern` keeps CLDR's short clock only when its hour field matches the requested
  cycle (quoted literals ignored), so marker-only rules still get the locale's marker placement.
  Otherwise it falls back to `HH:mm` or `h:mm a`.
- `date_text`: the rule branch is skipped for today and tomorrow unless `relative=False`, using a
  predicate of its own. Yesterday still takes the rules, and the existing `near` fallback for calls
  without rules is unchanged; CodeRabbit asked for this on #46.

Seven tests were added to [test/test_moments.py](test/test_moments.py). They cover marker-only
rules with 24-hour English, 12-hour French, Korean marker placement and the quoted `h` in fr-CA;
today and tomorrow with rules; yesterday with rules; and `relative=False` with rules.

Effect on skills: only thalovant-skill-date-time passes `rules=`. All 65 of its `written_form.json`
files carry both time patterns, and its written dates use `relative=False`, so its output does not
change. Its suite passes against this branch: 1467 passed, 2 xpassed (Python 3.12).

Verification: `ruff check thalovant_skillkit test scripts` is clean. `pytest -q` passes on Python
3.10 (627 passed, 32 skipped) and on Python 3.14 (631 passed, 28 skipped). Nothing is released;
publication runs only from a GitHub release.

### Transparency Report

- AI Model: Claude Opus 5.5 (Claude Code).
- Actions Taken: checked both review findings against `main` and reproduced them, changed
  `_time_by_rule` and `date_text`, added tests, ran the suite on 3.10 and 3.14 and the date-time
  skill's suite against the branch, and wrote the changelog entry, this report and `AUDIT.md`.
- Oversight: the change goes through a pull request with hosted CI before merge. No release.

## 2026-11-04: a layout may ask for the whole screen

**Changes**: `Card.fullscreen` (default off) and `display.layout(..., fullscreen=True)`; the
flag travels as `"fullscreen": true` in `meta["display"]` only when set. The satellite
keeps it for a layout card (thalovant-voice `feat/fullscreen-card`) and the screen draws
the layout edge to edge with no frame and no time along the top. For the guide skill's
thank-you mosaic of every OpenVoiceOS and HiveMind contributor.

**Verification**: `test/test_display.py` (one new: the flag in the dict when set, absent
otherwise); 32 of 32.

### Transparency Report
- **AI Model**: Claude Fable 5.1.
- **Actions Taken**: Added the field, the parameter and the test; a README sentence.
- **Oversight**: Asked for by the owner. Not reviewed by a human.

