# thalovant-skillkit

Write a Thalovant skill without writing the plumbing.

```bash
pip install thalovant-skillkit
thalovant-skillkit new garden-watering
```

That writes a complete skill — package, locales, tests, packaging, CI — that
passes its own checks before you touch it.

## The skill

```python
from thalovant_skillkit.skill import ThalovantFallbackSkill


class GardenWateringSkill(ThalovantFallbackSkill):
    FALLBACK_PRIORITY = 98

    def can_answer(self, message) -> bool:
        return self.mentions(self.utterance(message), "GardenWateringKeyword")

    def reply(self, utterance, lang, context):
        return self.dialog("garden.watering", lang)
```

`reply` is the one method most skills need. What it returns is spoken on the
hub and shown in the showroom, so the two cannot drift apart.

## A test

```python
from thalovant_skillkit.testing import message

def test_it_hears_its_keyword():
    assert GardenWateringSkill().can_answer(message("water the garden"))

def test_it_ignores_the_rest():
    assert not GardenWateringSkill().can_answer(message("set a timer"))
```

## Keeping it right

```bash
thalovant-skillkit check
```

Every locale complete, placeholders matching, packaging sound, priority in
band — and your sentences against every other skill's. Every skill's intents
are trained into one classifier on the hub, so a sentence you publish must
not already be another skill's: the check compares your `.intent` files with
the fleet's model on the Hugging Face Hub (`thalovant/thalovant-m2v-intents`,
public). A sentence another skill already publishes fails, on the line,
naming the owner; a sentence the classifier reads as another skill's warns,
with its confidence. The same check runs in the CI the scaffold writes for
you, on every push, and tells you which line to change. Offline, it says so
and checks the rest.

## What you get

| | |
|---|---|
| `self.utterance(msg)` | what was said |
| `self.lang_of(msg)` | the language of this utterance |
| `self.location_of(msg)` | where the house is |
| `self.mentions(text, "Voc")` | does the text mention this vocabulary — plurals included |
| `self.dialog("name", lang)` | a line from `locale/<lang>/dialog/name.dialog` |
| `self.setting("key", default)` | one skill setting |
| `self.reply(utterance, lang, ctx)` | your answer; spoken and previewed from one place |

There are four bases: `ThalovantSkill` for a skill with its own intents,
`ThalovantFallbackSkill` for one that answers what no intent claimed,
`ThalovantConversationalSkill` for one that keeps a conversation going, and
`ThalovantCommonPlaySkill` for one that answers OCP searches.

Everything on `OVOSSkill` still works — `self.speak`, `self.speak_dialog`,
`self.voc_match`, the intent decorators. Nothing here replaces them.

## Bounded conversation state

SkillKit 0.10 adds optional storage for application state. OVOS still owns
session IDs, conversation activation, scheduling, and playback.

```python
from thalovant_skillkit.sessions import SessionStateStore

states = SessionStateStore(max_entries=128, default_ttl=90)
states.set(session_id, {"round": 0})
with states.lock:
    game = states.get(session_id)
    if game is not None:
        game["round"] += 1
        states.set(session_id, game)  # explicitly refresh the idle timeout
states.remove(session_id)
```

Expiry uses a monotonic clock and is lazy. Reads do not extend a session;
writes refresh its expiry and its eviction position. Capacity evicts the
oldest write. Use `default_ttl=None` for state that should expire only on
explicit removal or capacity eviction. `remove(key, expected=value)` protects
cleanup based on an old snapshot from removing a replacement. `clear()` closes
all stored state. Store locking is per instance, and values remain mutable:
hold `states.lock` for compound updates. Keep blocking work outside that lock.
The skill decides whether anonymous sessions are allowed and when game turn
budgets are exhausted; the store does not infer identity or game rules.

## Integration tests with OVOS

```bash
python -m pip install 'thalovant-skillkit[testing]'
```

The optional testing extra targets the tested OVOS alpha stack and supplies
OvoScope. Existing `testing.message` and the recording `testing.FakeBus` remain
available for small unit tests. For actual dispatch and scheduling:

```python
from thalovant_skillkit.testing_ovos import skill_harness

with skill_harness(MySkill, skill_id="my-skill.example") as harness:
    # harness.skill uses the upstream dispatching FakeBus and real scheduler.
    harness.bus.emit(request)
```

`skill_harness` owns temporary settings, a native scheduler service, and cleanup,
even when a test fails. The scheduler answers requests without a timer thread
by default. `isolated_xdg()` restores environment variables and removes its
owned temporary directories; enter it before importing skills, usually from
`pytest_configure`. Upstream pytest plugins may already have imported OVOS, so
retain MiniCroft's configuration isolation as well.

`managed_minicroft(skill_ids, **options)` guarantees teardown.
`capture_turn(croft, message, timeout=30)` requires completion, detaches capture
listeners in `finally`, and returns recorded messages, spoken text, and the
originating session's latest state. Use that returned session for subsequent
turns. Other speakers' session updates are excluded. The opt-in
`deferred_capture_gc()` context scopes the documented OvoScope 1.8.5a1/pyee
12.1.1 finalizer workaround; other versions keep their normal GC policy.

## Check the built distributions

`check` keeps its fast source-contract and fleet checks. After building, validate
what will actually be installed:

```bash
python -m build
thalovant-skillkit check-artifacts --help
```

The stdlib-only API supports wheel and source-distribution checks together:

```python
from thalovant_skillkit.artifacts import check_artifacts

problems = check_artifacts(
    ".", wheel="dist/my_skill-1.0.0-py3-none-any.whl",
    sdist="dist/my_skill-1.0.0.tar.gz", package_dirs=["my_skill"],
    source_paths=["scripts/audio_sources"],
    wheel_excludes=["scripts/audio_sources/"],
)
assert not problems, problems
```

Checks compare bundled bytes with the source, reject missing resources and
unsafe or duplicate archive members, and verify matching distribution
identities. `source_paths` adds source-only rebuild inputs. Keep domain-specific
asset counts in the skill. Also install the wheel in a clean environment and
resolve its `opm.skill` entry point from outside the checkout; archive checks
do not substitute for plugin loading.

---

**Guide:** [docs.thalovant.com/developers/writing-a-skill](https://docs.thalovant.com/developers/writing-a-skill)
