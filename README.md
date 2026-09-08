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

Each function is the **union** of what the skills already did — the behaviour of
the most careful copy — so adopting it makes a thin skill more correct rather
than differently wrong.

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
