Last Edit: Claude Code (Claude Sonnet 5.5) - 2026-11-10 - Motive: 0.36.1, pacing no longer changes the words of a script written without spaces.
Previous: Last Edit: Claude Code (Claude Sonnet 5.5) - 2026-11-10 - Motive: 0.36.0, the SSML audit: a feature matrix tested against phoonnx, SPEECH_STYLE that reads every script and quantity, and `compat`.
Previous:  Claude Code (Claude Sonnet 5.5) - 2026-11-10 - Motive: 0.35.0, every SSML feature phoonnx speaks is accepted, checked and has a helper.
# Changelog

## 0.37.0

- **`thalovant_skillkit.device`: who is speaking, from the router's stamp only.** `device_identity(context)` and
  `device_allowed(context, allowed)` read the `device` and `device_name` the hub's home router writes into
  `context["thalovant_home"]` (which decides: every router since 0.4.1 overwrites it) and `context["thalovant_connector"]`
  (router 0.5.0; believed only when it names the same device: a client of an older hub could write that key itself)
  and nothing else. They fail closed (no stamp, a
  malformed stamp, an empty allow-list, an allow-list that raises: no). The module has no function that reads
  `context["peer"]`, `source`, `site_id` or `client_id`: those are the client's own words (a session called
  `x::1580::y` made the tail of `peer` read as another client's id). The retired `thalovant_music` stamp of an earlier
  router is not believed. The media skills and the Music Assistant skill each had a copy; they had begun to differ.
- **`thalovant_skillkit.safety`: titles to say, servers to dial.** `speakable` (tags, addresses, control and bidi
  characters out, one line, bounded), `contains_url`, `normalize_base_url`, `url_problem` (link-local and cluster-internal
  names, a plain `http://` or `ws://` to a public host), `address_problem` and `vetted_addresses` (the addresses a name
  resolves to now, each checked, so a name that answers differently the second time cannot move a client to cloud
  metadata). Reconciled to the most careful of the copies in the media skill, the shared media library and the Music Assistant
  skill: `speakable` removes an address as well as markup (the Music Assistant skill's copy spoke it).
- A skill whose floor is older than 0.37 imports both behind a guard (docs/reference.md, "Older kits"); the guard for
  `device` is to deny everyone. No existing name changed.

## 0.36.1

- **Fix: the pacing of scripts written without spaces no longer changes the words.** 0.36.0 paced Japanese,
  Chinese, Hindi and Arabic lines, and `to_plain` turned each pause into a space: `。ソース` read back
  as `。 ソース`. A skill that shows or compares the plain text (the news and custos-fallback tests did)
  saw text that differed from its dialog. A pause after a mark of such a script (`。！？।؟、，：；` and
  closing quotes) now adds no space; where the dialog wrote a space, it stays.

## 0.36.0

- **`thalovant_skillkit.compat`: use a kit name without making the skill unloadable.** A hub keeps
  the kit it imported at boot while it installs a newer skill, so a module-level
  `from thalovant_skillkit.ssml import SpeechStyle` against an older loaded kit raised
  `ImportError` and the skill stopped answering. `speech_style_or_none(**fields)` and
  `ssml_helper(name)` ask the *loaded* kit (so they also work when the files on disk are newer);
  `kit_attr`, `kit_version` and `kit_at_least` are the building blocks. No existing name changed.
- **`SPEECH_STYLE` pauses in every script the skills ship.** The sentence, comma, colon and
  semicolon marks of Japanese, Chinese, Hindi, Arabic and others (`。！？ ， 、 ； ： । ؟ ، ؛ ۔`) are
  marks without a space after them, so a line in `ja`, `zh` or `hi` was never paced (about 40
  of the weather skill's lines gained a pause). No space is added where the language wrote none.
- **`SPEECH_STYLE` no longer pauses inside an abbreviation.** `Dr. Smith`, `M. Dupont`, `St. Louis`,
  `J. R. Smith`, `9 a.m. on Monday`, `Nov. 9`, `am 9. November` and `9 – 5` are not sentence or
  clause ends; `It was 9 p.m. Then it rained.` still is.
- **`SpeechStyle(say_as=True)` (the default) wraps literal quantities in `<say-as>`.** A `14 h 30`,
  `7:30 pm`, `3,50 €`, `$12.50`, `23 °C`, `15 km/h`, `10 %`, `1er`, `3rd`, `1,200` or numeric date in
  a dialog is read with the language's own rules instead of the voice's text normalizer, which
  says "quatorze h trente", "trois virgule cinq euros" and "un deux cents". Only English, French,
  German, Spanish, Italian, Portuguese and Dutch (`ssml.SAY_AS_LANGUAGES`); a placeholder is
  wrapped only directly before `%` or `°C`. `auto_twin(template, style, lang=None)` takes the
  language; without it the pauses are all that is derived.
- **The validator names each mistake precisely.** A `<break>` with a negative time is "negative",
  not "needs a unit"; a `<prosody>` with nothing to change, a `<phoneme>` with an empty `ph` or one
  holding `[[`/`]]`, a `<say-as format>` on anything but a date or time, and a `<phoneme>` holding
  tags are reported. `<w role>` and `interpret-as` `letters` and `verbatim`, which phoonnx reads,
  are accepted.
- **Values lose what XML cannot carry.** A NUL or other control character in a value from a
  service made the whole line "not well-formed" and cost it its markup; `escape` and the helpers
  now drop them from the SSML (the plain words are unchanged).
- **Tests:** one parametrised matrix (`test/ssml_matrix.py`) of every construct, run against the
  kit alone and against phoonnx's own `parse_ssml` (CI job `ssml_phoonnx`, 1.96.2a2), plus
  synthesis through a real English and French voice when one is at hand.

## 0.35.0

- **Everything phoonnx can speak is something a skill can write.** `validate`, `check` and
  `markup` now accept `<prosody pitch>` (`+2st`, a percentage or a name), `<say-as>` with
  `cardinal`, `ordinal`, `fraction`, `unit`, `date` (+`format`), `time`, `currency`, `address`,
  `expletive` and `interjection`, `<phoneme alphabet="x-sampa">`, `<mark>`, `<amazon:effect>`
  (whispered, drc, soft, vocal-tract-length), `<amazon:auto-breaths>`, `<amazon:breath>` and
  `<amazon:domain>`. Other prefixed tags, `<audio>` and Hz pitches are still reported.
- **Helpers for each:** `cardinal`, `ordinal`, `fraction`, `unit`, `currency`, `address`,
  `interjection`, `expletive`, `as_date`, `as_time`, `phoneme`, `prosody`, `pitch`, `whisper`,
  `soft`, `compress`, `vocal_tract`, `breath`, `auto_breaths`, `mark`. Each refuses what a voice
  would not read, and its plain words are the written text.
- `SpeechStyle` gains `pitch` and `breaths`.
- The voice needs phoonnx with SSML support to speak them; on an older voice they are read as
  plain words, and the plain `utterance` is unchanged either way.

## 0.34.0

- **`SPEECH_STYLE`: pace a skill's replies without a `.ssml` twin per line.** A
  skill class sets `SPEECH_STYLE = SpeechStyle(rate=..., sentence_break=...,
  colon_break=..., dash_break=..., comma_break=...)` and `speak_dialog` sends
  `utterance_ssml` derived from the dialog line's own words (`ssml.auto_twin`).
  Rules read the template, never the filled-in values; a hand-written twin still
  wins for its line; without the attribute nothing changes. Skills that copied
  every line into a twin only to add pauses can delete the twins.
- `checks.redundant_twins(root, style)` reports twins the style already says.

## 0.33.0

- **The runtime group's service token reaches the platform's services.** A new
  module, `service_auth`, reads the token from the file named by
  `THALOVANT_SERVICE_TOKEN_FILE` and sends it as `Authorization: Bearer` to the
  seven shared services in namespace `thalovant` (`SERVICE_HOSTS`), and to no
  other host. `post_json`, `JsonServiceClient.post` and `ask_service` (so
  `knowledge_reply` too) add it; `request_headers` adds it when given the new
  `url=` keyword. Headers built for a service lose the token when sent anywhere
  else, `JsonServiceClient` keeps it off redirects, and a caller's own
  `Authorization` is left alone. Without the file nothing changes.
- **A 401 from a service is asked once more** when the token file then holds a
  different token (the file is also re-read whenever it changes). It does not
  count as an attempt, and the same token is never sent twice.
- **Skills that call a service with their own `requests` call** get no token
  until they pass `url=` to `request_headers`.
- **A Redis that lost its data no longer brings back records people deleted.**
  The import marker was kept only in the first backend, Redis. After a restart
  without persistence it was gone, so `load_all_with_legacy` imported the old
  document again into Redis and PostgreSQL, and an alarm deleted since the import
  came back. The marker is now written to every backend (PostgreSQL's first) and
  read from all of them: `done` in any one is done, and a backend without it is
  given it, which also repairs a marker PostgreSQL could not take at the import.
  `PostgresBackend.migration_finish` now inserts the row when PostgreSQL did not
  hold the claim (beside a Redis it never does). A backend that could not take the
  marker, or could not be asked, owes it: `save_changes` gives it the marker
  before anything else, and until it has it that backend takes no save (its part
  fails like any other, and the skill sends the change again), so a delete never
  reaches PostgreSQL before its marker. (CodeRabbit on #52.)
- **After Redis refuses the old document's key, PostgreSQL's copy is still read.**
  0.31.2 stopped the import for the life of the process at the first refusal,
  even when PostgreSQL had failed at the same moment, so the old records stayed
  out until a restart. A refusal now only stops the Redis read:
  `JsonStateStore.load(redis=False)` reads PostgreSQL alone, at most every five
  minutes, as for any store that has not yet given a document. Redis is still
  asked once. (CodeRabbit on #54.)
- **`JsonStateStore`'s PostgreSQL comes back after a failure.** A failed connect
  turned PostgreSQL off for the life of the store, and a connection PostgreSQL
  closed (a restart, a failover) stayed in use, failing every load and save. A
  connect that fails is now tried again after `POSTGRES_RETRY_SECONDS` (60 s), and
  a connection that fails a query is closed and replaced on the next call. A
  missing `psycopg` still turns it off, once.
- Docs: `docs/records.md`'s example now sets `self._records` before the first
  load, and its per-turn read sends a change an earlier save could not make
  before it reads that owner afresh (the read used to replace it in both lists);
  the guide no longer says Redis runs Lua. The 0.31.0 entry below said a failed
  save "leaves nothing half written", which was never true: it now says what a
  failed save can leave written.
- Docs: the README's Quickstart and the reference's `[testing]` install pinned
  0.31.1 through the 0.31.2 and 0.32.0 releases. A reader copying them got the
  kit that still runs Lua on Redis. Both now pin the release they ship in, and
  `test_the_documented_install_pins_the_version_this_is` fails when a version
  bump leaves them behind. (CodeRabbit on #22 found the same thing at 0.14.0.)

## 0.32.0

- **`RecordStore` no longer uses Lua on Redis.** A record changes in one `MULTI`, and a delete watches the owner's hash. Redis doesn't count a script's memory against `maxmemory`, so a login that can load a script can take down a shared Redis with one script, and every skill in a runtime can read this login. A limited Redis user now needs `MULTI`, `EXEC`, `DISCARD`, `WATCH`, `UNWATCH` and `HEXISTS`, and no longer needs `EVALSHA` or `SCRIPT LOAD`. **Grant the new commands before a runtime takes this version:** without them every save is refused and the skill keeps its change in memory.

## 0.31.2

- **`THALOVANT_RECORDS_REDIS_URL` on its own now switches `RecordStore` on.** The store
  took the URL after `enabled` had been decided, so a runtime with only this variable
  reported no database and every record skill stayed on its settings, with no warning.
- **A Redis user that may not read the old whole-document key is asked once.** The import
  retried every five minutes for the life of the process, with a warning and an entry in
  Redis's ACL log each time. A refusal now stops the retries for that process; an
  unreachable Redis is still tried again.

## 0.31.1

- **`RecordStore` can run under a Redis user that may touch only some keys.**
  `key_prefix` in the settings, `<PREFIX>_KEY_PREFIX` or `THALOVANT_RECORDS_KEY_PREFIX`
  (that order) replaces the leading `thalovant` of every Redis key: the records, the
  owner set and the import marker are `<prefix>:records:v1:<scope>:<key>:...`. A
  prefix is validated (segments of letters, digits, `_`, `.`, `-` joined by single
  colons, at most 200 characters); a bad one turns Redis off with one warning and
  leaves PostgreSQL working. Unset, the keys are exactly what 0.31.0 wrote.
  `THALOVANT_RECORDS_REDIS_URL` is one Redis URL for every record skill in a
  runtime (after `<PREFIX>_REDIS_URL`, before `REDIS_URL`).
- **A Redis that refuses (`NOPERM`, `WRONGPASS`, `NOAUTH`) is one warning, once.**
  It names the key prefix, the key pattern and commands the ACL needs
  (`REDIS_ACL_COMMANDS`) and the settings that move the keys; the skill falls back
  as before and `RecordStoreError.acl` is True on a save. Other failures still
  warn every time.
- Docs: `docs/records.md`, "Operators: running under a per-hub Redis user" (the
  OvosRuntime `$(VAR)` recipe, URL-escaping the password, the exact ACL).
- Not changed: the old `JsonStateStore` key stays `thalovant:<scope>:<key>` (a
  prefix there would orphan existing documents).

## 0.31.0

- **`RecordStore`: a person's records, kept one at a time under that person.**
  `JsonStateStore` keeps every owner's records as one document under one key and
  writes all of it back on each save, so two people, or two hub pods, saving
  together overwrote one another, and each pod's copy went stale. The alarm,
  reminder, timer and stopwatch skills all stand on it. `thalovant_skillkit.records`
  keeps a Redis hash per owner and a PostgreSQL row per record (both set: Redis is
  read, PostgreSQL keeps a copy and refills an emptied Redis), written by one Lua
  step or one transaction per record; `save_changes(before, after)` writes only
  what differs, by owner and id, and never touches another owner's records;
  `load_all`, `load_owner`, `splice_owner`/`replace_owner`, `owners`. The owner is
  hashed into every key and row (`owner_key`), so no label, "a" and "a:b", empty,
  unicode or enormous, can reach another's data; a record with no owner field
  lives in `_unowned`. It reads the same settings and environment as
  `JsonStateStore` (`redis_url`, `redis_sentinel_urls`, `database_url`,
  `<PREFIX>_REDIS_URL`, `REDIS_URL`, `<PREFIX>_DATABASE_URL`, `DATABASE_URL`,
  `<PREFIX>_STATE_KEY`): an operator changes nothing. With no database it returns
  None and writes nothing, and the skill keeps its settings. A write that
  cannot be made raises `RecordStoreError`; it can leave part of the change
  written (the other backend, or in Redis the records before the failure), so a
  skill keeps the snapshot of its last successful save and the next save sends
  the change again. *(Corrected after release: this said the write "leaves
  nothing half written".)*
- **The old document comes over once, and is left alone.** `migrate_legacy` (and
  `load_all_with_legacy`, the call a skill makes at its start) imports the
  whole-document records into the new layout: put only where absent, so anything
  newer wins; one pod claims the import (a claim not finished within five minutes
  may be taken over, the import being repeatable); the marker is set only after a
  document was read, so a legacy store that was merely unreachable is tried again;
  the old document is never modified or deleted.
- `testing.FakeRecordStore` is the real store over an in-memory backend for a
  skill's unit tests (diff saves, per-owner records, migration, and
  `backend.fail = OSError(...)` to rehearse a database that is down).
- A guide for skill authors: `docs/records.md` (the swap from
  `_state_store().save()` to `save_changes(before, after)`, the per-turn read of
  one owner, the migration call, how to look at a person's records in Redis and
  PostgreSQL, the limits).
- Tests: 89 in `test/test_records.py` run on memory, fakeredis (which runs the
  real Lua) and the real SQL over a sqlite adapter; with
  `THALOVANT_RECORDS_TEST_REDIS_URL` and `THALOVANT_RECORDS_TEST_DATABASE_URL`
  the same suite runs on a real Redis and PostgreSQL (CI starts both).

## 0.30.0

- **Python 3.11 is the floor.** The kit said 3.10 while every project it
  generates, the docs and the README's own quickstart said 3.11, and the floor
  kept Dependabot's security update for `filelock` red: all thirteen advisories
  against the 3.x line (GHSA-v4x8-3wr5-3wq8, high, and twelve beside it) are
  fixed in 4.2.1, which needs 3.11. `requires-python` is `>=3.11`, the `tomli`
  fallback is gone (`tomllib` is in the standard library from 3.11), the CI
  matrix runs 3.11, 3.12 and 3.14, and the classifiers say 3.11 to 3.14.

- **The lock takes `filelock` 4.2.9.** combo-lock 0.3.1, under ovos-utils, still
  requires `filelock~=3.0`, so the project's `uv.lock` overrides that one
  requirement (`[tool.uv] override-dependencies`), recorded in the lock's
  manifest. combo-lock's own suite gives the same result on 3.32.7 and 4.2.9,
  and this kit's suite runs on 4.x from the lock. The override governs this
  lock only: a `pip install thalovant-skillkit` still resolves filelock 3.x
  until combo-lock widens its requirement (forslund/combo-lock#28).

- **The fallback base answers the message it was given.** `handle_fallback`
  spoke with `self.speak(text)`, which finds the message it answers by walking
  the stack and speaks in `self.lang`; it now calls `speak_to(message, text)`,
  the kit's own advice for a reply from any thread, so the room that asked
  hears it in its language. A skill that overrides `handle_fallback` is
  unaffected. A test double that captured fallback replies by overriding
  `speak` should override `speak_to` (the `testing` harnesses listen on the
  bus and need no change).

- `fold_tight`'s docstring says what it keeps (ASCII letters and digits) and
  what that means for a non-Latin identifier; the display cards' `as_dict`
  methods carry docstrings; a test proves `layout_file` reads the layout
  beside the module that defines the skill's class, not only that it fails
  elsewhere. The `tokenizers<1` pin stays: model2vec 0.10.0 still calls
  `Tokenizer.get_vocab()` and tokenizers 1.0.0 is at rc3.

## 0.29.2

- **What the satellite would refuse is refused when the card is built, with a
  reason.** Three review findings on #47 that 0.29.0 shipped without: a layout's
  `data` accepted `NaN` and infinity (`json.dumps` allows them, the satellite's
  strict reader does not); a layout's `image` was not checked to be bytes, so a
  path raised `TypeError` instead of `CardError`; and a figure (`weather`,
  `item`) or a tap's `at` too large for a float raised `OverflowError` -- out of
  the builder, or out of the bus handler, which dropped the tap with a traceback.
  Each is now a `CardError`, and for the tap report, a report that is not
  believed.

- **A knowledge answer that is not a document is a failed request.**
  `ask_service` returned whatever JSON the service sent on the plain path; a
  list or a string reached `knowledge_reply`, which raised `AttributeError` on
  `.get` and failed the turn. It is now the `ValueError` the streamed path
  already raised for a malformed answer, and `knowledge_reply` reports an
  unavailable answer.

- The `check` notes that pointed at the empty `[fleet]` extra now say that
  `model2vec` is not installed, which the base install carries. The README's
  quickstart pins this release instead of 0.22.0 and shows `moments` and the
  lookup notice; the reference documents `moments`, the lookup notice and
  `ask_service`, `speak_to(display=)`, `layout(fullscreen=)` and the new
  refusals, and its `[testing]` pin follows the release. The publish workflow
  pins the artifact actions by commit, as every other step is. `uv.lock`
  follows the OVOS prereleases CI installs (ovoscope 1.12.1a1, ovos-workshop
  9.10.1a1, ovos-core 3.7.5a1), so `test_real_core_sends_a_twin_with_the_fallback_reply`
  passes from the lock as it does in CI.

## 0.29.1

- **A layout's text travels with every card.** 0.29.0 sent it inline the first
  time a hub process sent that layout and by hash afterwards, assuming one
  satellite. A hub serves many: on 2026-11-05 a probe asking the weather took
  the one inline copy of the forecast layout, and the Mark II, asking a minute
  later, got a hash it did not have and drew the words with `layout_missing`.
  `Card.as_dict()` now always carries `rfw` with `sha256` (at most 64 KB, a few
  KB in practice); the satellite still keeps layouts by hash.
  `forget_sent_layouts()` stays as a no-op for 0.29.0 callers.

## 0.29.0

- **A skill can show something on a satellite with a screen.** `display` builds
  a card -- `text`, `list_card`, `weather`, `media`, or a `layout` of the
  skill's own from `gui/thalovant/<name>.rfwtxt` -- and `display.showing(card)`
  puts it in `meta["display"]` of every reply spoken inside the block;
  `speak_to(..., display=card)` and `speak_varied_dialog(..., display=card)`
  take it directly (`speak` and `speak_dialog` keep OVOS's signatures). The
  satellite's sizes are checked when the card is built, so a card it would
  not show raises `CardError` here. A layout's text travels once per process
  and by hash afterwards. A tap on a card's button comes back as
  `thalovant.display.action`; `add_display_action_handler` delivers it as a
  `display.Tap` for this skill's cards only.

- **A locale's written rules no longer overrule the clock or the relative day.**
  `time_text(..., written=True, rules=...)` with a rule set that carries only the
  am/pm markers fell back to CLDR's short clock, which is the locale's own 12- or
  24-hour preference: an English 24-hour request came back as "10:18 p.m." and a
  French 12-hour one as "22:18". The short clock is now used only when it keeps the
  asked-for cycle (so Korean still writes "오후 10:18"); otherwise the fallback is
  `HH:mm` or `h:mm a`. `date_text(..., written=True, rules=...)` returned an
  absolute rule-formatted date even for today and tomorrow; those now keep
  "today"/"tomorrow" unless the caller passes `relative=False`, as the docstring
  says. Yesterday still takes the rules.

- **A malformed stream event is a failed request, not a crash; an unknown one is
  skipped.** 0.27.0 checked each line's shape but let an `event` it did not know
  through, and the reader then took it for an error and raised `KeyError` on its
  missing `detail`, which `knowledge_reply` does not catch, so the turn failed. An
  event of a kind the kit does not know (`progress`, or `Answer` in another case) is
  now skipped and the answer that follows is still read, so a service that adds an
  event never costs an older kit its answers. A source, answer or error without the
  fields it needs, an error whose `status` is `true` or `false`, a line that is not
  an event and a stream that ends without an answer are a `ValueError`, which
  `knowledge_reply` turns into an unavailable answer.

- `uv.lock`: certifi 2026.7.22 to 2026.10.19 (#45, Dependabot).

## 0.28.0

- **No more silent seconds, and no guessing how long to wait.** 0.27.0 named the
  source that answers, but waited a fixed half second after hearing it in case the
  answer followed at once, and said nothing at all while the providers were still
  being asked. The service now says whether a slow step (translating the answer, or
  the model writing it) follows the source it announces, and both are known before
  they start (thalovant/thalovant-knowledge-service#167):
  - a slow step follows (`pending: true`): "From Wikipedia…" the moment the source
    is known, about 0.5 s in, instead of 0.5 s later;
  - none follows (`pending: false`): nothing, the answer is on its way;
  - an older service that does not say: the half-second wait of 0.27.0, as before.
- **"Looking it up…" when nothing has come back after `WORKING_DELAY` (1.2 s).** A
  provider that is slow to answer left the visitor with a blank chat for as long as
  it took, and there is nothing true to name until a source is chosen, so this line
  names nothing. It is said once per turn, and the source is still named after it
  when one is announced. It also covers a service that does not stream at all.
- `ask_service` reads the reply on its own thread and the calling thread decides when
  to speak, so a reply that is slow to send its first byte no longer blocks the notice.
- `working_text(lang)` is the localized line, in the eleven hub languages.

## 0.27.0

- **The notice names the source that answers, not a list of those asked.** 0.26.0
  said "Checking Wikipedia and DuckDuckGo…" after 0.6 s, which named sources that
  did not answer and, for a research question, five of them. The knowledge service
  now says which source it has chosen as soon as it has (it is known before the
  answer is translated and written, which is where the seconds go), and the visitor
  is told "From Wikipedia…" only when the answer is still not there `NOTICE_DELAY`
  (0.5 s) after that. An answer that follows at once, one from the cache and one
  that needs no provider say nothing first. Needs the service from
  thalovant/thalovant-knowledge-service#166; against one without it the request is
  answered in plain JSON, as before, and nothing is said.
- `ask_service(...)` is the one place a skill posts a question to the service. It
  asks to hear the source when a notice is open, reads the stream, and raises what
  `requests` raises, so `knowledge_reply` and a skill with its own request use the
  same code. An `error` line after the source carries the status the plain reply
  would have had, so a 404 is still "no answer".
- `provider_name(id)` gives the name a visitor knows a provider by, and
  `notice_text(lang, provider)` the localized line. The line is now one source
  ("From {source}…", "Selon {source}…", …) in each of the eleven hub languages.
- `run_noticing` is deprecated and only runs its work: it was the 0.26.0 way for a
  skill with its own request, and the skills written for it still import and answer.
  Use `ask_service`.

## 0.26.0

- **A slow lookup says where it is looking.** A question put to the knowledge
  service takes a few seconds, because the service asks its providers in
  parallel and waits for the good ones, and the chat stayed blank (a voice
  device, silent) for all of it. A skill now opens `lookup_notice(speak)` where
  it has the message to answer, and when a knowledge call under it takes longer
  than `NOTICE_DELAY` (0.6 s) the visitor is told "Checking Wikipedia and
  DuckDuckGo…" while the request carries on. A quicker lookup says nothing, and a
  turn says it once however many lookups it makes. Research mode names the
  paper sources too (OpenAlex, Crossref, arXiv).
- `knowledge_reply` does this on its own request, so a skill that already
  calls it only has to open the notice. A skill with its own request wraps it
  in `run_noticing(work, lang=..., mode=...)`. With no notice open, neither
  changes anything.
- The notice has a line in each of the eleven languages the public hubs serve
  (`shared_dialog/<lang>/dialog/knowledge.notice.dialog`; any other language
  reads the English one, joined with English punctuation). It sits beside
  `locale/`, not in it: every folder there is a matching language and must
  declare a matching rule.
- `LookupNotice.names(provider)` says whether the notice already named a
  source, for a skill that cites where its answer came from and would otherwise
  say it twice. The service's `web-search` counts as DuckDuckGo.

## 0.25.0 (unreleased)

- **Folding keeps the marks that spell a letter.** `strip_accents`, and with
  it `fold`, `fold_spaces` and `fold_words`, dropped every combining mark. That
  is right for an accent and wrong where the mark is the letter: the Hindi
  virama went ("क्रिकेट" folded to "करिकेट"), the Thai tone marks went ("โป้"
  and "โป๊" folded to one word) and so did the kana voicing marks ("何かある"
  and "何がある"). `fold_words` then cut every Hindi and Thai word at its
  vowel signs, which `\w` does not match: "खेल समाचार" became "ख ल सम च र", so
  no Hindi news topic matched. Marks in the Brahmic and South-East Asian
  scripts (Devanagari, Bengali, Gurmukhi, Gujarati, Oriya, Tamil, Telugu,
  Kannada, Malayalam, Sinhala, Thai, Lao, Tibetan, Myanmar, Khmer and their
  neighbours) and the kana voicing marks now stay, on both sides of every
  comparison. The nukta still folds: Hindi writes "दरवाज़ा" and "दरवाजा" for one
  word, and the fleet lists both. Latin, Greek and Cyrillic diacritics, Arabic
  harakat and Hebrew niqqud fold as before.
- Over the fleet's 217,587 vocabulary, intent and entity lines, the three
  functions return the same bytes as 0.24.2 in 64 of 68 languages. The four
  that change are hi-IN, th-TH, ja-JP and one ko-KR line that contains Gurmukhi.
  Lines that folded identical without being the same line: hi-IN 217 to 90
  under `fold_words` (what is left differs only by a nukta or by punctuation),
  th-TH 20 to 10, ja-JP 14 to 12 (punctuation only).
- **`contains_term` treats a kept mark as part of the word.** The word-start
  rule used `\w`, so a Hindi term could start or end beside a vowel sign in the
  middle of a word: "क" claimed "किताब". `text.WORD_CHAR` is the character class
  to use instead of `\w` over folded text, and `text.KEPT_MARKS` the marks it
  adds.

## 0.24.2 (2026-10-03)

- **The model download skips the hubs' encoder.** intent-corpus now publishes
  the prototype encoder the hubs match with under `encoder/` in the same Hub
  repository as the fleet classifier. The check reads only the classifier at
  the root, so `resolve_model` leaves `encoder/` out and every skill's CI keeps
  downloading what it did before, not another 120 MB.

## 0.24.1 (2026-10-03)

- **The classifier check reads the model's own threshold per language.**
  intent-corpus now measures, per language, the confidence at which no more
  than 1 % of held-out sentences would be reported as another skill's, and
  publishes it in the model's `training.json` (`thresholds`). `check
  --fleet-only` uses it: French and German come out at 0.96, so a French
  sentence the model gives another skill at 0.95 is no longer reported. A
  model without the key keeps the shared 0.9, and an explicit threshold still
  applies to every language.

## 0.24.0 (2026-10-03)

- **Intent lines expand the way OVOS expands them.** `intents.expand` now
  hands the line to ovos-spec-tools, the expander the engines call, instead of
  a parser of its own that knew `(a|b)` and nothing else. `[x]` and `[a|b]`
  are optional, and `<name>` stands for the lines of `<name>.voc` in that
  language (`intents.vocabularies`). The fleet corpus is built with these
  functions, and it carried 3,513 sentences with a literal `[` in them (home
  3,263, volume 249) and 266 volume sentences with a literal `<level>`, so the
  duplicate check never compared home's or volume's real sentences. Rebuilt
  with this release, home publishes 18,161 sentences instead of 13,442 and
  volume 6,903 instead of 1,926, and one cross-skill duplicate appears: oc-FR
  "mai fòrt", in joke-garden and volume.
- A line OVOS refuses now raises `MalformedTemplate` from `expand` (it used to
  pass through unexpanded), and publishes no sentence from `intent_lines`:
  OVOS skips it, so the fleet does not hear it either.
- **`check` fails an intent line OVOS skips**, with `file:line` and what to
  write instead: brackets that do not pair, a line that is only a `{slot}`, a
  `<name>` with no `.voc`, a `|` outside a group, and the other malformed forms
  of OVOS-INTENT-1 section 3.6. The verdict is ovos-spec-tools' own. Every
  locale directory is read, and the check also runs under `check --fleet-only`,
  the gate every skill's CI runs. On the fleet today it fails date-time (fi-FI,
  hu-HU), weather (et-EE, lt-LT, vi-VN) and source-scout (az-AZ, eu-ES, ja-JP,
  ko-KR); each has a pull request that fixes the lines.
- A pipe outside a group is refused on ovos-spec-tools 1.13, which the hubs
  pin, as it is on 1.14, which refuses it itself, so both read the same lines.
- ovos-spec-tools logs a warning for each `(word)` group it folds to `word`.
  The kit filters that one warning out while it expands, so `check` does not
  print one for each such line in the fleet.

## 0.23.0 (2026-10-01)

- **Tables move out of `vocab/`.** A `canonical|alias|alias` line in a `.voc`
  no longer loads: ovos-spec-tools 1.14 expands every `.voc` line by
  OVOS-INTENT-1, where a `|` outside `(a|b)` is an error, and ovos-workshop
  9.8.9 expands every `.voc` under the locale tree when a skill registers an
  intent with a vocabulary blacklist, so one such line stops the skill
  loading. A table the skill parses itself now lives in
  `locale/<lang>/tables/<name>.table`. The locale check reports any `.voc`
  line with a pipe outside a group, and runs the collapsed-alias check on
  `.table` files as it did on `.voc` ones.
- `new` no longer writes a CI step that dispatches `skill-merged` to the
  intent corpus. It needed a personal access token that no skill repository
  holds, so it only ever printed a warning; the corpus rebuilds hourly on its
  own.

## 0.22.0 (2026-09-26)

- **Speech markup.** A reply can carry SSML as `utterance_ssml` beside the plain
  `utterance`, which keeps plain words and never a tag. thalovant-voice 0.7.3
  reads it; the Android app and the Kotlin SDK say the plain words.
- A dialog gets markup from a twin: `locale/<lang>/dialog/<name>.ssml` beside
  `<name>.dialog`, line for line, with the same `{placeholders}`.
  `speak_dialog`, `speak_varied_dialog`, `dialog` and the fallback base draw one
  line and send both forms of it, with the values escaped in the SSML. A twin is
  optional in every locale and never borrowed from another one. The name is
  `.ssml` and not `.ssml.dialog` because OVOS reads every `.dialog` as a plain
  template and raises on a `<break/>` in one.
- `thalovant_skillkit.ssml` builds markup in Python: `say`, `pause`, `spell`,
  `digits`, `telephone`, `foreign`, `emphasis`, `sub` and `markup`. Each returns
  a `Speech`, a `str` of the plain words that also carries the SSML. Passed as a
  dialog value, a `Speech` marks up that value in a dialog with no twin, in every
  language. Plain strings are escaped, so text from a user or a service never
  becomes markup.
- The kit's bases override `speak` and `speak_dialog` with OVOS's own signatures.
  Without markup they hand the call to OVOS unchanged. With markup they send the
  message OVOS would send, with the same context, meta, language and wait, and
  `utterance_ssml` added. `speak_to` sends a `Speech` the same way and gains
  `wait`.
- SSML written into a plain string is moved to `utterance_ssml` before it is sent,
  and logged once per skill, so no tag reaches a client that shows `utterance`.
- `check` validates every twin: well-formed, only the tags Thalovant voices
  render, the same placeholders and the same words as its plain line, and as many
  lines. A plain `.dialog` may not hold SSML tags. The rule also runs under
  `check --fleet-only`, the gate every skill's CI runs. The fleet's 24 skills
  have no twins and no tags in their dialogs, so all of them pass unchanged.
- A region in `regional.json` that rewords a dialog without its twin no longer
  inherits the base locale's twin for that dialog.
- `FakeBus.spoken_ssml()` and `CapturedTurn.spoken_ssml` expose the markup sent
  with each sentence, lined up with `spoken`.
- Markup written as a whole `<speak xml:lang="...">` document, in a twin or a
  string, gets one root when it is sent: the language becomes a `<lang>` inside
  it. It used to be nested in a second `<speak>`, which SSML forbids. Found by
  review on this release.
- `speech_topic()`, which `speak_to` and the markup path both use, now calls the
  installed `OVOSSkill.speak` once on a stand-in skill and uses the topic it
  emitted. It no longer infers it from what the workshop module imports. Checked
  on ovos-workshop 8.0.0 (`speak`, with ovos-spec-tools 1.13 installed beside it),
  9.8.6a2 and 9.8.9a2 (`ovos.utterance.speak`). This closes the review finding on
  0.21.0.

## 0.21.1 (2026-09-25)

- `speak_to` asks the installed workshop's skill module which topic its own
  `speak()` emits on, instead of assuming the spec topic whenever the spec
  package is importable. Workshop 8 forwards on legacy `speak` even with
  `ovos-spec-tools` installed beside it, and a reply on the other topic is a
  reply nobody hears. Found by review on 0.21.0.
- `speak_to` checks for a bus before building the message, so a reply that
  cannot be sent fails first and builds nothing.

## 0.21.0 (2026-09-25)

- Add `self.speak_to(message, text, *, lang=None, expect_response=False,
  written=None, meta=None)` on every SkillKit base, and `speech.speak_to(skill,
  message, text, ...)` for skills on other bases. It forwards the message you
  were given, so the reply keeps that message's session and reaches the room
  that asked, in that message's language. Every game in the fleet and the quiz
  tutorial were building this message by hand; `self.speak` cannot do it,
  because it walks the call stack for a message and speaks in `self.lang`.
- `moments.speak_with_written` now builds its message through the same
  primitive, which means it speaks on the installed workshop's spec topic
  (`ovos.utterance.speak`) instead of the legacy `speak` when the spec
  package is present. The fallback for a test skill without a bus is unchanged.

## 0.18.0 (2026-09-22)

- Share bounded network reads, context-local reply deadlines and per-URL failure
  cooldowns through `RequestBudget` and `JsonServiceClient`. Requests are attempted
  once; skills choose their unavailable reply. Existing `post_json` is unchanged.
- Add `PeriodicWorker` for cancellable background refresh, `JsonStateStore` for
  the household skills' existing Redis/PostgreSQL format, and a conversational
  Common Play base that preserves native OVOS playback and conversation hooks.
- Make startup requirements independent of runtime requirements through optional
  base-class flags, so online skills can load and offer an offline fallback.
- Add bounded caches for bundled file inventories and combined locale resources,
  with explicit invalidation. These store filenames and text, never audio bytes
  or user replies. Add `ShuffleBagPool` and `speak_varied_dialog` for varied sounds
  and translated replies without copied selection bookkeeping.
- Document adoption, cache lifetimes, failure behavior and performance measurement.
  Optional storage drivers remain lazy imports; no new base runtime dependency.

## 0.17.0 (2026-09-22)

- **A conversational base now answers the converse ping instead of raising.**
  ovos-workshop 9 made `can_converse` an abstractmethod whose body is
  `raise NotImplementedError`. Nothing enforces it -- `OVOSSkill` is not an
  ABC -- so a skill that overrode `converse()` and not `can_converse()`
  loaded perfectly, answered no `<skill_id>.converse.ping`, and its
  `converse()` was never called once. From the outside it reads as a skill
  ignoring the answer to its own question.

  `thalovant-skill-alarm` 0.1.17 shipped exactly that and was caught on a
  real phone. `thalovant-skill-reminder` and `thalovant-skill-custos-shadow`
  both inherit these bases and were in the same state; they pick this up
  with no change of their own, since both allow a newer skillkit.

  True is the honest default: it is what ovos-workshop 8 did, and every
  skill here is written for it, opening `converse()` with its own guards. A
  skill should still override with a cheap, pure probe where it can.

## 0.16.1 (2026-09-21)

- **Hold `tokenizers` below 1.x.** `model2vec` asks for `tokenizers>=0.20` with
  no upper bound, and `tokenizers` 1.x dropped `Tokenizer.get_vocab()`.
  `model2vec` 0.9.0 -- the newest there is -- calls it twice
  (`model.py:54` and `:72`), so any install that resolves to 1.x raises
  `AttributeError: 'tokenizers.Tokenizer' object has no attribute 'get_vocab'`
  the moment the fleet check loads a model.

  Only pre-releases of 1.x exist today (`1.0.0rc1`, `rc2`), so it bites
  anything installed with `--pre` and nothing else -- which is how it was
  found, in the documentation site's tutorial job. It stops being selective
  the day 1.0.0 goes stable, and then it is every install, including the hub
  runtime. Lift the bound when `model2vec` supports 1.x.

## 0.16.0 (2026-09-20)

- Add `ThalovantConversationalFallbackSkill`: a fallback skill that can also
  finish what it started. `converse()` on `ThalovantFallbackSkill` was dead
  code -- the converse plumbing (`activate`, `deactivate`, the
  `ovos.converse.ping` acknowledgement) lives on ovos-workshop's
  `ConversationalSkill`, and a skill only answers that ping when its
  `skill_id` is in `session.converse_handlers`, which a class without
  `activate()` can never arrange.

## 0.15.0 (2026-09-19)

- Add `thalovant-skillkit locales [directory] [--write]`: generate complete OVOS
  resources from a shared language and explicit regional overrides. The default
  only checks; normal `check` also detects missing or stale generated resources.
- Keep regional authoring offline and out of the request path. Validate source
  languages, paths and placeholders before writing; preserve existing base locales
  and report obsolete files instead of deleting them.
- Document regional translation provenance, native intent compatibility, and
  the difference between inherited wording and a reviewed local translation.

## 0.14.0 (2026-09-19)

- Resolve regional language tags through shared OVOS/CLDR language and script
  relationships. Exact overrides and parent tags win; reference locales replace
  alphabetical selection. Missing regional files try compatible translations
  before the configured default. `matching_langs` exposes this chain without
  an unrelated default. Resource selection never changes the session language.
- Preserve BCP-47 script, extension and private-use subtags when normalizing
  messages. Partial regional vocabularies and literal intent examples inherit
  their language's phrases without mixing unrelated languages into intent matching.
- Declare the language matcher dependencies explicitly and document regional
  overrides, speech-language preservation and script/translation boundaries.
- Accept repeated-digit numbers such as `11` in vocabulary checks. Document a
  file-local `# skillkit: literal-alias <text>` exception for words with natural
  repetition; other aliases on the same line are still checked.

## 0.13.0 (2026-09-18)

- `check` now reports a translated `.voc` alias that swallowed the list it
  belonged to. A line is `canonical|alias|alias|...`; a translator handed the
  aliases as one unit answers with one string, joined by a comma, by a space or
  by nothing at all, and the line then offers one long alias nobody would say.
  Found live: every non-English locale of the reminder and alarm skills had lost
  its repeat cadences this way, so "remind me every day" was recurring in English
  and a silent one-off in thirty other languages. The two tells are a comma and
  the same words twice running, in the target language's punctuation as well as
  English's. Counting fields is deliberately not one of them:
  French weather has no abbreviation for Monday, and a count calls all seven of
  its weekdays broken.

## 0.12.0 (2026-09-13)

- Add opt-in session-filtered captured turns and decoded audio records for
  testing speech, queued sound bytes and Stop routing across speakers. Existing
  unfiltered capture and speech behavior is unchanged.
- Add `selection.ShuffleBag` for non-repeating sounds or dialog, with independent
  state, seeded randomness and explicit previous-choice avoidance per speaker.
- Gate pull requests and publication on installing the built wheel in a fresh
  environment, generating skills and testing their installed packages outside
  the source checkout.

## 0.11.3 (2026-09-13)

- Fix the generated English and French test phrases to pass the question-only
  gate introduced in 0.11.2. Generated tests also reject room chatter, including
  when it contains a topic keyword. SkillKit's CI now creates projects with
  ordinary and question-word names and runs their tests.
- Reuse the embedding model and classifier across languages within each fleet
  check. A later check loads fresh artifacts; empty comparisons load no model.
- Restore the corpus round-trip assertion for both repository identity and SHA.

## 0.11.2 (2026-09-13)

- A generated skill's `can_answer` goes through `claims()` before its keyword
  test, and the generated class sets `QUESTIONS_ONLY = True`, so the gate
  applies to new skills as well as to the ones that set it by hand.

## 0.11.1 (2026-09-13)

- Add `ThalovantFallbackSkill.QUESTIONS_ONLY`, `asks()` and `claims()`: a fallback
  that sets the flag considers only sentences that ask something, by the
  language's own question words (thalovant-languages 0.3.0). Measured on
  2026-09-12, keyword nets answered room chatter that merely held a word.

## 0.11.0 (2026-09-13)

- Add `bus.wait_for_response` for requests sharing a response topic: explicit
  correlation predicate, one finite timeout, and listener cleanup on success,
  timeout or error. Used by live Custos queries and persona rewrites to isolate
  simultaneous callers without serializing them.
- Generated CI now rebuilds a wheel from its source distribution and checks
  both artifacts against source resources, catching files missing from releases.
- Add cached `SkillResources.matches_literal_intent` so fallback skills can
  recognize their own concrete localized examples without broad keyword gates
  or treating slot/alternative patterns as literal phrases.

- Expand the README into a verified installation-to-package walkthrough and
  add an API/CLI reference for released 0.10.0 behavior. Clarify locale fallback,
  session ownership, test isolation, check limitations, and service outcomes.
- Correct inline API documentation without changing runtime behavior.

## 0.10.0 (2026-09-12)

- Add an opt-in `SessionStateStore` with bounded capacity, monotonic expiry,
  per-instance locking, snapshot iteration, and identity-checked removal.
  Session identity and game rules remain the consumer's responsibility.
- Add optional OVOS/OvoScope integration helpers for isolated XDG/settings,
  native scheduler fixtures, guaranteed teardown, completed conversation
  capture, and propagation of the originating session's latest state.
- Keep the known OvoScope capture-finalizer workaround explicit and limited to
  the affected version combination. Existing recording test doubles remain
  unchanged.
- Add offline `check-artifacts` CLI and API validation of wheel/sdist resources,
  bytes, metadata identities, archive paths, duplicates, and optional inventory
  counts. Preserve the existing fast source-contract checks.
- Add dedicated CI jobs exercising optional integration helpers. Keep text and
  locale performance checks independent from opt-in stateful storage.
