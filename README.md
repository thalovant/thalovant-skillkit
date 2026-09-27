# thalovant-skillkit

Build and test Thalovant skills for Open Voice OS (OVOS) with shared message,
locale, conversation, and packaging helpers. SkillKit provides base classes, a
project scaffold, and checks for skill resources and built packages. OVOS owns intent routing, speech,
sessions, and scheduling.

## Quickstart

You need Python **3.11 or newer** with `venv` and `pip`, a terminal, and access to
your Python package index. SkillKit itself supports Python 3.10 and newer; its
generated projects require 3.11. No running hub or speaker is needed here.

Start in a working directory where `thalovant-skill-garden-watering` does not
already exist:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --pre "thalovant-skillkit==0.22.0"
thalovant-skillkit new garden-watering
cd thalovant-skill-garden-watering
python -m pip install --pre -e ".[test]" build
thalovant-skillkit check
python -m pytest -q
```

This example pins SkillKit 0.22.0. `--pre` allows the current OVOS prerelease
stack; see the [reference](docs/reference.md#tested-ovos-environments) for legacy
Workshop 8 compatibility.

You should have a fallback skill with **five passing tests**, English and French
locale resources, package metadata, and a GitHub test workflow. The check reports
`ok: thalovant-skill-garden-watering keeps its contracts`. This scaffold uses
vocabulary files, so it has no intent examples for fleet comparison. The workflow
tests and validates packages; it does not install your skill on a speaker.

The sample answers `what is garden watering` with a placeholder reply and
declines ordinary room chatter. Edit
`thalovant_skill_garden_watering/__init__.py` for its behavior and `locale/` inside
that package for vocabulary and replies. Both initial vocabularies use the same
English keyword; translate them before calling the skill translated.

Regional tags such as `en-CA`, `en-GB`, and `fr-CA` reuse compatible translations
while retaining the speaker's language. For regional wording, keep only the differences
in `locale/regional.json`; `thalovant-skillkit locales --write` builds complete OVOS
resources. See the [regional guide](https://docs.thalovant.com/developers/writing-a-skill/#support-regional-variations).

## Speech markup

A reply can carry SSML beside its plain words: a pause, a code read one
character at a time, a word in another language. The Thalovant voice app reads
the markup. Clients that only read the plain words, such as the Android app,
say the same sentence without it. SkillKit never puts a tag in the plain words.

**A pause before a punchline.** Put a twin beside the dialog, one line for each
line of the dialog, with the same `{placeholders}`. For
`locale/en-US/dialog/joke.dialog`:

```text
Why did the scarecrow win an award? Because he was outstanding in his field.
```

write `locale/en-US/dialog/joke.ssml`:

```text
Why did the scarecrow win an award? <break time="700ms"/> Because he was outstanding in his field.
```

`self.speak_dialog("joke")` and `self.dialog("joke", lang)` pick a line and send
both forms of that line. A language without a twin says its plain line.

**Spelling a code.** Mark up the value instead of the dialog. This works in every
language the skill ships, with no locale file to change:

```python
from thalovant_skillkit.ssml import spell

self.speak_dialog("code", {"code": spell("XK7")})
```

**A word in another language.** Build the sentence in Python:

```python
from thalovant_skillkit.ssml import foreign, say

self.speak_to(message, say("One", foreign("café au lait", "fr-FR"), "coming up."))
```

A plain string passed to these helpers is escaped, so what a user said can never
become markup. `thalovant-skillkit check` checks every twin, and so does
`check --fleet-only`. The [reference](docs/reference.md#speech-markup) lists the
helpers, the tags a voice renders and the rules.

## Continue building

- [Writing a Skill](https://docs.thalovant.com/developers/writing-a-skill/) — choose
  a base class and understand how a skill works with OVOS.
- [SkillKit tutorial](https://docs.thalovant.com/developers/skillkit-tutorial/) —
  build a bilingual educational quiz with sounds, one working lesson at a time.
- [API and CLI reference](docs/reference.md) — helper contracts, session state,
  native OVOS testing, resource lookup, and command options.
- [Changelog](CHANGELOG.md) — releases and upgrade notes.

## Contribute

From a SkillKit checkout, activate a virtual environment and run the same lint
and unit checks as CI:

```bash
python -m pip install --pre -e . pytest ruff
python -m ruff check thalovant_skillkit test scripts
python -m pytest -q
```

For changes to native OVOS integration, also follow the integration job in
[the test workflow](.github/workflows/test.yml). Its optional dependencies and
harness contracts are covered in the [reference](docs/reference.md#test-helpers).
Report reproducible problems or suggest improvements in
[GitHub issues](https://github.com/thalovant/thalovant-skillkit/issues).
