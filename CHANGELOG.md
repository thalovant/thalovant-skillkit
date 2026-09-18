# Changelog

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
