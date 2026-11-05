Last Edit: Claude Code (Claude Fable 5.1) - 2026-11-05 - Motive: Release 0.29.2, the review follow-ups left open on #47 and #48, a knowledge body that is not a document, and the stale lock.
Previous:  Claude Code (Claude Sonnet 5.5) - 2026-11-05 - Motive: Release 0.29.1, a layout's text travels with every card.

# Maintenance report

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

