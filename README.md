# thalovant-skillkit

Build and test Thalovant OVOS skills with shared message, locale, conversation,
and packaging helpers. OVOS owns intent routing, speech, sessions, and scheduling;
SkillKit helps your skill use them consistently.

Start below, follow the [skill-writing guide](https://docs.thalovant.com/developers/writing-a-skill/),
or look up an API in the [reference](https://github.com/thalovant/thalovant-skillkit/blob/main/docs/reference.md).

## Create your first skill

Use Python **3.11 or newer** for this generated project. SkillKit itself supports
Python 3.10 and newer. Run these commands from a working directory where
`thalovant-skill-garden-watering` does not already exist:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install "thalovant-skillkit>=0.10.0"
thalovant-skillkit new garden-watering
cd thalovant-skill-garden-watering
python -m pip install -e ".[test]" build
thalovant-skillkit check
python -m pytest -q
```

With SkillKit 0.10.0, this produces a fallback skill, five passing tests, locale
resources, package metadata, and a GitHub test workflow. No running hub is needed.
The generated workflow tests the project; it does not publish or install it on a
speaker. Package installation requires access to your Python package index.

The generated `en-US` and `fr-FR` files are starting points. Both initially use
`garden watering` as their keyword. Translate the French vocabulary and replace
the sample replies before describing your skill as translated.

| Change | File inside the generated project |
| --- | --- |
| What it recognizes | `thalovant_skill_garden_watering/locale/<lang>/vocab/GardenWateringKeyword.voc` |
| What it says | `thalovant_skill_garden_watering/locale/<lang>/dialog/garden.watering.dialog` |
| How it answers | `thalovant_skill_garden_watering/__init__.py` |
| Languages checked for completeness | `thalovant_skill_garden_watering/locale/supported.json` |
| Version and dependencies | `thalovant_skill_garden_watering/version.py` and `pyproject.toml` |

For example, add `water the garden` on its own line in the English `.voc` file
if you want that wording recognized. Keep recognition narrow so the skill yields
to unrelated requests.

## Write the answer

The generated class passes the incoming message's language to vocabulary matching:

```python
from thalovant_skillkit.skill import ThalovantFallbackSkill


class GardenWateringSkill(ThalovantFallbackSkill):
    FALLBACK_PRIORITY = 98

    def can_answer(self, message) -> bool:
        return self.mentions(
            self.utterance(message), "GardenWateringKeyword", self.lang_of(message)
        )

    def reply(self, utterance, lang, context):
        return self.dialog("garden.watering", lang)
```

For this fallback base, OVOS calls `can_answer` before `reply`. A nonempty answer
is spoken; `None` or an empty answer yields to another fallback. Keep `can_answer`
cheap. Put service calls in `reply`, set timeouts, and decide what to say when a
service cannot answer. `preview_reply()` calls the same reply logic and returns
text without speaking; it does not run intent routing. If you override
`initialize()`, call `super().initialize()` to retain fallback registration.

These tests can be saved as `test/test_readme.py` in the generated project:

```python
from thalovant_skillkit.testing import message

from thalovant_skill_garden_watering import GardenWateringSkill


def test_recognizes_the_generated_keyword():
    assert GardenWateringSkill().can_answer(message("garden watering"))


def test_leaves_other_requests_alone():
    assert not GardenWateringSkill().can_answer(message("set a timer"))
```

## Choose a base for the job

Import these classes from `thalovant_skillkit.skill`:

| Base | Use it for | Implement |
| --- | --- | --- |
| `ThalovantSkill` | Explicit intents | OVOS intent handlers; `reply` is not registered automatically |
| `ThalovantFallbackSkill` | A narrow topic earlier intents did not handle | `can_answer` and `reply`; fallback priority 91–100 |
| `ThalovantConversationalSkill` | Follow-ups tied to a conversation | Intent handlers, `can_converse`/`converse`, and stop cleanup |
| `ThalovantCommonPlaySkill` | Open Common Play search providers | OVOS Common Play search handlers; needs the upstream Common Play base |

`ThalovantCommonPlaySkill` is `None` when the upstream Common Play base cannot
be imported. Keep the corresponding OVOS lifecycle hooks and decorators. A conversational
base does not create application state or claim every next turn. See the
[reference](https://github.com/thalovant/thalovant-skillkit/blob/main/docs/reference.md) for runtime requirements, resource lookup, and
helper defaults.

## Keep conversations separate

SkillKit 0.10.0 adds `SessionStateStore`. Create one store **per skill instance**,
key it by the incoming OVOS session ID, and choose an explicit policy for messages
without an ID. This standalone example demonstrates the storage operations:

```python
from thalovant_skillkit.sessions import SessionStateStore

states = SessionStateStore(max_entries=128, default_ttl=90)
session_id = "example-room"
states.set(session_id, {"round": 0})
with states.lock:
    game = states.get(session_id)
    if game is not None:
        game["round"] += 1
        states.set(session_id, game)  # renew expiry after an accepted turn
assert states.remove(session_id)
```

Reads do not renew the timeout. Expiry is lazy and uses a monotonic clock;
capacity evicts the oldest write. Values remain mutable, so hold `store.lock`
around compound updates and keep blocking I/O and playback waits outside it.
Use `remove(key, expected=old_value)` when cleanup must not remove a replacement.

On session Stop, remove that session's state and cancel its scheduled work using
OVOS. Storage expiry and `clear()` do not stop audio, deactivate OVOS sessions,
or cancel timers. The skill still owns follow-up relevance and turn limits.

## Test at the right level

| Test | What it establishes |
| --- | --- |
| Unit tests with `testing.message` and the recording `testing.FakeBus` | Logic and emitted messages; handlers are not dispatched |
| `testing_ovos.skill_harness` | Native bus dispatch, settings isolation, and scheduler behavior |
| `testing_ovos.managed_minicroft` and `capture_turn` | Utterance routing and conversations through OVOS/OvoScope |
| A speaker and human reviewers | Recognition, audible timing, sound quality, and natural language |

Install the optional integration stack into a test environment:

```bash
python -m pip install --pre "thalovant-skillkit[testing]>=0.10.0"
python -m pip check
```

This can upgrade OVOS to prereleases. The `[skill]` and `[fleet]` extras are
compatibility names; their dependencies are already in the base installation.
The `[testing]` extra is optional. The scaffold's own `[test]` extra supplies
pytest, but does not create an E2E suite.

The [guide's integration examples](https://docs.thalovant.com/developers/writing-a-skill/#exercise-the-real-ovos-bus)
show complete fixtures and assertions. Isolate XDG paths before importing skills,
retain MiniCroft's configuration isolation, and carry the session returned by
`capture_turn` into follow-ups. The [reference](https://github.com/thalovant/thalovant-skillkit/blob/main/docs/reference.md) explains cleanup,
scheduler defaults, and the version-specific `deferred_capture_gc()` workaround.

## Validate source and built packages

Run these from the generated project after its tests pass:

```bash
thalovant-skillkit check
python -m build
thalovant-skillkit check-artifacts . \
  --wheel dist/thalovant_skill_garden_watering-0.1.0-py3-none-any.whl \
  --sdist dist/thalovant_skill_garden_watering-0.1.0.tar.gz
```

Use the filenames produced by your build if you change the project or version.
`check` validates source contracts and, for skills with `.intent` files, compares
their examples with the fleet. New exact ownership conflicts fail; already-recorded
overlaps, classifier predictions, and near matches are reported without failing.
A locally unavailable model is reported as skipped;
in GitHub Actions it fails. `check --no-fleet` explicitly runs only source checks.
The generated fallback uses `.voc` files, so it has no fleet intent examples to
compare yet. Passing checks does not prove recognition or translation quality.

`check-artifacts` reads supplied archives offline, compares package resources
byte for byte with the checkout, and checks archive structure and metadata. It
does not change packaging configuration. For a `src/` layout, select the package
explicitly, such as `--package src/thalovant_skill_garden_watering`. Additional
options cover generator sources, wheel exclusions, and asset counts; see the
[reference](https://github.com/thalovant/thalovant-skillkit/blob/main/docs/reference.md). Before release, also install the wheel in a separate
environment and verify plugin discovery from outside the checkout.

## Upgrade an existing skill

To adopt the 0.10.0 store or artifact checker, raise the skill's dependency to
`thalovant-skillkit>=0.10.0`. Add `[testing]` only to integration-test dependencies.
Importing a helper does not migrate existing state or fixtures: preserve session
identity, expiry rules, Stop behavior, and assertions as you replace local code.
Test two independent sessions, expiry, Stop, and an unrelated request before
publishing the built wheel.

Working examples are [Fart 0.5.0](https://github.com/thalovant/thalovant-skill-fart/tree/v0.5.0),
[Custos Shadow 0.1.3](https://github.com/thalovant/thalovant-skill-custos-shadow/tree/v0.1.3),
and [Custos Query 0.1.4](https://github.com/thalovant/thalovant-skill-custos-query/tree/v0.1.4).

## Troubleshoot the first run

| Symptom | Check |
| --- | --- |
| Cannot import the generated package | Enter its directory and run `python -m pip install -e ".[test]"` in the active environment |
| A phrase is not recognized | Add it to the correct locale's vocabulary or intent; use the message's language |
| Another language answers in English | Check the requested locale and resource files; fallback can hide a missing translation |
| A dialog name is returned instead of text | Check the dialog file and its presence in the installed wheel |
| `FakeBus.emit()` invokes no handler | `testing.FakeBus` records; use `skill_harness` for native dispatch |
| A scheduled test event never fires | The harness timer thread is off by default; drive `tick()` or use `scheduler_autostart=True` |
| Fleet comparison was skipped locally | Restore model access/cache or use `--model`; a skipped check is not a fleet pass |
| Archive validation finds missing files | Correct packaging configuration, rebuild, and check the new archives |

See the [API and CLI reference](https://github.com/thalovant/thalovant-skillkit/blob/main/docs/reference.md) for exact behavior. Report
reproducible problems in [GitHub issues](https://github.com/thalovant/thalovant-skillkit/issues).
