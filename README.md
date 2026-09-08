# thalovant-skillkit

Write a Thalovant skill without writing the plumbing.

```bash
pip install "thalovant-skillkit[skill]"
```

## A skill

```python
from thalovant_skillkit.skill import ThalovantFallbackSkill


class NewsSkill(ThalovantFallbackSkill):
    FALLBACK_PRIORITY = 96

    def can_answer(self, message) -> bool:
        return self.mentions(self.utterance(message), "NewsKeyword")

    def handle_fallback(self, message) -> bool:
        self.speak(self.dialog("headlines", self.lang_of(message)))
        return True
```

That is the whole skill. Your `locale/` tree is found for you, the fallback is
registered once at a priority an operator can change, and the language of each
utterance is read from wherever the satellite put it.

`ThalovantSkill` is the same for a skill that answers its own intents and needs
no fallback.

## A test

```python
from thalovant_skillkit.testing import MONTREAL, message


def test_it_answers_in_french():
    assert NewsSkill().can_answer(message("les nouvelles", lang="fr-FR"))


def test_it_knows_where_it_is():
    NewsSkill().handle_fallback(message("what time is it", location=MONTREAL))
```

`message()` builds what the satellite really sends. Without a location, a skill
that tells the time is tested in Kansas.

## What you get

| | |
|---|---|
| `self.utterance(msg)` | what was said |
| `self.lang_of(msg)` | the language of this utterance |
| `self.location_of(msg)` | where the house is |
| `self.mentions(text, "Voc")` | does the text mention this vocabulary — plurals included |
| `self.dialog("name", lang)` | a line from `locale/<lang>/dialog/name.dialog` |
| `self.setting("key", default)` | one skill setting |

`self.speak`, `self.speak_dialog`, `self.voc_match` and everything else on
`OVOSSkill` still work — nothing here replaces them.

## Also inside

`message`, `text`, `vocab` and `locale` are usable on their own, without the
skill framework, for code that is not a skill. `knowledge` is the client for the
Thalovant knowledge service.

---

**Full guide:** [docs.thalovant.com/developers/writing-a-skill](https://docs.thalovant.com/developers/writing-a-skill)
