# thalovant-skillkit

Shared plumbing for the Thalovant OVOS skills.

## Why

Twenty-three skills grew the same private helpers independently. An audit across
the fleet found **36 functions living in three or more skills — about 1,600
duplicated lines** — and that they had drifted apart:

| function | skills | distinct implementations |
|---|---|---|
| `_resource_lang` | 19 | 8 |
| `_message_lang` | 18 | 10 |
| `_utterance` | 17 | 5 |
| `_resource_lines` | 16 | 10 |
| `_fold` | 15 | 9 |

Plus `knowledge_client.py`: 210 lines, vendored **byte-identically into three
skills**, kept in step by a convention written in its own docstring and by a
"platform contracts gate" that does not exist in the platform repository.

Drift is not a tidiness problem:

- Five skills matched their vocabularies with `term in text`, so ops-copilot's
  `log` matched "techno**log**y" and the ops copilot answered *"what's the
  latest news about technology"* with **"Paste events or logs."** — in English
  and French alike. Fixing it meant the same edit in five repositories, and the
  sixth skill would have inherited the bug.
- Five skills read the utterance language from `context["lang"]` only, so an
  utterance carrying its language in `data` or in the session was answered in
  the wrong language.
- Six skills still call the deprecated `standardize_lang_tag` and print a
  deprecation warning on every utterance.

## What's here

| module | what it replaces |
|---|---|
| `message` | reading utterance, language, session and location off a `Message` |
| `text` | folding text so a vocabulary line and a spoken phrase compare |
| `vocab` | whether an utterance contains a term, without claiming "podcast" |
| `locale` | a skill's own `locale/` tree: language choice, lines, dialog, voc |
| `fallback` | the ladder rung, an operator override, registering once |
| `service` | request headers with a traceable id, and a POST that stays quiet |
| `knowledge` | the knowledge-service client, previously vendored three times |

## Language data lives in `locale/`, not in Python

How a vocabulary term may match is a fact about a language, so it sits in
`thalovant_skillkit/locale/<lang>/matching.json` beside everything else the
fleet keeps per language — the same convention the skills and `thalovant-voice`
use.

```json
{ "word_separated": true, "inflection_max": 3 }
```

- **`word_separated`** — false for Japanese, Korean, Thai and Chinese, which do
  not put spaces between words, so a boundary means nothing and a term is
  matched by containment.
- **`inflection_max`** — how many letters a term may pick up and still be the
  same word: `log` → "logs", `explique` → "expliquer", while `pod` must not
  reach "podcast".

A language with no file of its own inherits `en-US`, the same way a skill's
locale does. Only the languages whose behaviour is actually known are shipped:
Turkish, Finnish and Hungarian stack suffixes and three letters is plainly too
tight for them, but the right number is a claim about a language and none is
invented here.

Each function is the **union** of what the skills already did — the behaviour of
the most careful copy — so adopting it makes a thin skill more correct rather
than differently wrong.

## Writing a skill

Inherit and write the skill. The base class carries the plumbing:

```python
from thalovant_skillkit.skill import ThalovantFallbackSkill


class NewsSkill(ThalovantFallbackSkill):
    FALLBACK_PRIORITY = 96

    def can_answer(self, message) -> bool:
        return self.voc_match("NewsKeyword", self.utterance(message),
                              self.lang_of(message))

    def handle_fallback(self, message) -> bool:
        self.speak(self.dialog("headlines", self.lang_of(message)))
        return True
```

That is the whole skill. No `LOCALE_DIR`, no `_utterance`, no `_message_lang`,
no `_resource_lang`, no `_fold`, no `_dialog`, no thirteen-line
`runtime_requirements`, and no fallback registration to get right — the locale
tree is found from the module the class lives in, the fallback is registered
once at a priority an operator can override in settings, and every helper is a
method.

An audit of the fleet found **194 such functions across 22 skills, about 1,600
lines**, that no skill needs to write again. The smallest skill was 369 lines
and 23% of it was this.

### What you get

| on the skill | what it does |
|---|---|
| `self.utterance(message)` | the text, from whichever key the message carries it under |
| `self.lang_of(message)` | the language, from data, context or session |
| `self.location_of(message)` | the house's location, or `None` |
| `self.voc_match(name, text, lang)` | vocabulary match that does not claim words merely spelling a term |
| `self.voc_term(name, text, lang)` | the matching term itself, longest first |
| `self.dialog(name, lang, data)` | a rendered line, picked at random, falling back to English |
| `self.setting(key, default)` | one setting, readable before the skill is bound |
| `self.resources` | the `SkillResources` for this skill's `locale/` |
| `REQUIRES_NETWORK/INTERNET/GUI` | three attributes instead of a `RuntimeRequirements` block |

`ThalovantSkill` is the same without the fallback machinery, for a skill that
only answers its own intents.

## Testing a skill

Thirteen skills hand-roll a fake message, and no two agree — some set a
language, some do not. A skill tested only against language-less messages is
tested against something the satellite never sends.

```python
from thalovant_skillkit.testing import FakeBus, MONTREAL, message

def test_it_answers_in_french():
    skill = NewsSkill()
    assert skill.can_answer(message("quelles sont les nouvelles", lang="fr-FR"))

def test_it_knows_where_it_is():
    skill = NewsSkill()
    reply = skill.handle_fallback(message("what time is it", location=MONTREAL))
```

`message()` builds what the satellite actually sends — a real
`ovos_bus_client.Message` when that is installed, a faithful stand-in when it is
not. `FakeBus` records what a skill said (`bus.spoken()`) and what it
registered.

## Use

```python
from pathlib import Path
from thalovant_skillkit import SkillResources, message_lang, utterance, resolve_priority

RESOURCES = SkillResources(Path(__file__).parent / "locale")
FALLBACK_PRIORITY = 98


class MySkill(FallbackSkill):
    def can_answer(self, message) -> bool:
        lang = message_lang(message, self.lang)
        return RESOURCES.voc_match("MyKeyword", utterance(message), lang)

    def _fallback_priority(self) -> int:
        return resolve_priority(self._skill_settings(), FALLBACK_PRIORITY)
```

`SkillResources` is bound to one skill's locale directory, which is what kept
these functions from being lifted out before — each skill read its own
`LOCALE_DIR` module constant.

## The one behaviour change

`utterance()` reads `phrase`, `text` and `query` as well as `utterance`, because
OCP search, converse and the showroom preview send those. Fifteen skills read
only the first and returned `""` on the other three paths. A skill adopting this
will find text where it previously found none — which is the point, but it means
`can_answer` can now answer where it used to decline.
