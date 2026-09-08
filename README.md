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

---

**Guide:** [docs.thalovant.com/developers/writing-a-skill](https://docs.thalovant.com/developers/writing-a-skill)
