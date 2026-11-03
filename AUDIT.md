Last Edit: Claude Code - 2026-11-03 - Motive: Record the moments rule fallback findings and their fix.

# Audit

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
