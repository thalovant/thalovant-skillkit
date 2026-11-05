Last Edit: Claude Code (Claude Fable 5.1) - 2026-11-05 - Motive: Whole-kit review for 0.29.2: the open review findings, the knowledge client's plain path, the lock and the records.
Previous:  Claude Code (Claude Sonnet 5.5) - 2026-11-05 - Motive: Release 0.29.1, a layout's text travels with every card.

# Audit

## 2026-11-05 whole-kit review (0.29.2)

Every module under `thalovant_skillkit/` was read, with the CodeRabbit threads on #19 to #49.

- Fixed (Minor, #47 outside the diff): `display.layout` accepted non-finite floats in `data`; `display.layout` took a non-bytes `image` to a `TypeError`; `display.tap` and `display._figure` raised `OverflowError` on an integer too large for a float. Evidence: reproduced on 0.29.1 (`tap({... "at": 10**400})`, `layout(data={"t": nan})`, `layout(image=("a path", "image/png"))`, `weather(temperature=10**400)`). Tests: the nine new cases of `test_what_the_satellite_would_not_show_fails_here` and the two in `test_a_tap_on_this_skills_card_reaches_the_handler`.
- Fixed (Major): `knowledge.ask_service` handed a non-object body to `knowledge_reply`, which raised `AttributeError` and failed the turn. Evidence: reproduced with a fake `requests.post` returning a list, a string and an integer, with and without a notice. Test: `test_a_body_that_is_not_a_document_is_a_failed_request_on_both_paths`.
- Fixed (test): `test_real_core_sends_a_twin_with_the_fallback_reply` depended on OVOScope's default pipeline, which omits the low fallback band when adapt and padatious are installed. Evidence: a probe of the captured turn showed `ovos.intent.unmatched` with the pipeline list ending at `ovos-fallback-pipeline-plugin-medium`. The test names `FALLBACK_PIPELINE`.
- Fixed (records): README quickstart at 0.22.0; reference without `moments`, the lookup notice, `speak_to(display=)` and `layout(fullscreen=)`, `[testing]` at 0.12.0; `check` notes naming the empty `[fleet]` extra; `publish.yml` artifact actions by floating tag; the certifi bump missing from the 0.29.0 changelog (#48, the one CodeRabbit thread still open).
- Open: Dependabot's security update for `filelock` fails on `main` because the patched versions need Python 3.11 and `requires-python` is `>=3.10`; raising the floor is the owner's call. `handle_fallback` speaks with `self.speak(text)` rather than `speak_to(message, ...)`; OVOS resolves the session's language from the handler's stack, so it answers the room that asked, but a skill answering from another thread should call `speak_to`. `fold_tight` keeps ASCII letters and digits only, which its docstring ("letters and digits") understates for a non-Latin identifier. `display.showing` is thread-local, as recorded on 2026-11-04. `SkillResources.dialog` catches `KeyError`/`IndexError` and not `ValueError`, as the reference says. None of these changed behaviour here.
- Checked and sound: `text.py` (the kept-marks table and `WORD_CHAR`), `vocab.py`, `locale.py`, `message.py`, `fallback.py`, `service.py`, `bus.py`, `sessions.py`, `selection.py`, `network.py`, `workers.py`, `storage.py`, `regions.py`, `intents.py`, `fleet.py`, `checks.py`, `ssml.py`, `artifacts.py`, `moments.py`, `speech.py`, `cli.py`'s scaffold against the docs' "Writing a Skill" page, and the kit's display limits against thalovant-voice `src/thalovant_voice/display.py` on `main` (identical constants; the satellite drops a `lang` that is not a tag rather than refusing the card).

## 2026-11-04 review follow-up on #47

- Fixed: `_skill_root` in `thalovant_skillkit/display.py` resolved a class argument through its metaclass. Evidence: CI run 41912545035 failed `test/test_display.py::test_the_layout_is_read_beside_the_skills_module` on 3.10, 3.12 and 3.14 (the C `_abc` metaclass has no source file, `inspect.getfile` raised `TypeError`, and `CardError("cannot find the skill's directory")` came out instead of "not found"); locally the test passed only because the `abc` module's directory holds no layout. The class is now resolved when a class is passed.
- Fixed: the module docstring's two examples called `speak_dialog` / `speak` with `display=`, which those OVOS-signature methods do not accept.
- Open: `test_the_layout_is_read_beside_the_skills_module` asserts the failure text, not the directory searched; a test that plants a layout beside the fixture skill and reads it would prove the lookup positively.


## 2026-11-04 display cards

- `display.showing` keeps the pending card in a thread-local; a handler that speaks from another thread it started (a worker) does not see it, and must pass `display=` to `speak_to` instead. Evidence: `test/test_display.py::test_a_showing_block_attaches_the_card_to_every_reply_inside` runs on one thread.
- `layout_file` reads the file on every call; a skill answering often should keep the `Layout` it returns. The sent-once set (`_sent_layouts`) was removed in 0.29.1: it was per process, not per satellite, so only the first satellite to ask got the text (the Mark II, 2026-11-05).
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
