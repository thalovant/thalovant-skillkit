Last Edit: Claude Code (Claude Fable 5.1) - 2026-11-04 - Motive: Display cards: what a skill shows on a satellite with a screen, and the tap that comes back.

# Maintenance report

## 2026-11-04 display cards for a satellite with a screen

- **Contents:** `thalovant_skillkit/display.py` (new): builders for the card a satellite with a display draws from `meta["display"]` -- `text`, `list_card`, `weather`, `media`, `layout` with `layout_file` reading `gui/thalovant/<name>.rfwtxt` -- `action`, `item`, `clear`, `attach`, the `showing` context manager and `pending`, and `tap` for the `thalovant.display.action` report. `skill.py`: `speak` and `speak_dialog` attach a pending card (their OVOS signatures unchanged, as `test_the_speech_overrides_keep_the_framework_signatures` requires); `speak_to` and `speak_varied_dialog` take `display=`; `_SkillPlumbing.add_display_action_handler` follows the tap event once and delivers `Tap`s for this skill's cards.
- **Sizes:** the satellite's own bounds (thalovant-voice `display.py`) are mirrored as constants and checked when a card is built, so a card that will not be shown raises `CardError` here with the reason. A layout's text travels inline once per process and by `sha256` afterwards.
- **Verification:** `ruff check` clean on the three files; `test/test_display.py` (new, 26 tests) and the whole suite: 690 passed with `[testing]` on this machine.
- **Not done here:** no skill uses it yet (the weather skill's card is its own change); the control-plane grant for `thalovant.display.action` is thalovant-api's; the reference's version line still says 0.18.0, as before.
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
