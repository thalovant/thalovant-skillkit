Last Edit: Claude Code (Claude Sonnet 5.5) - 2026-11-05 - Motive: Release 0.29.1, a layout's text travels with every card.

# Maintenance report

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

