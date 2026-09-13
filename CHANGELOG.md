# Changelog

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
