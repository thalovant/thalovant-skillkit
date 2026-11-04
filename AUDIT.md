Last Edit: Claude Code (Claude Fable 5.1) - 2026-11-04 - Motive: Display cards: what a skill shows on a satellite with a screen, and the tap that comes back.

# Audit

## 2026-11-04 display cards

- `display.showing` keeps the pending card in a thread-local; a handler that speaks from another thread it started (a worker) does not see it, and must pass `display=` to `speak_to` instead. Evidence: `test/test_display.py::test_a_showing_block_attaches_the_card_to_every_reply_inside` runs on one thread.
- `layout_file` reads the file on every call; a skill answering often should keep the `Layout` it returns. The sent-once set (`_sent_layouts`) is per process: after the hub restarts, the first card sends the text again, which is the intent, but a satellite that lost its cache between two cards is not told until the skill calls `forget_sent_layouts()`.
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
