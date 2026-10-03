# Changelog

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
