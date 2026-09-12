# Changelog

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
