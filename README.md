# thalovant-skillkit

Build and test Thalovant skills for Open Voice OS (OVOS) with shared message,
locale, conversation, and packaging helpers. SkillKit provides base classes, a
project scaffold, and checks for skill resources and built packages. OVOS owns intent routing, speech,
sessions, and scheduling.

## Quickstart

You need Python **3.11 or newer** with `venv` and `pip`, a terminal, and access to
your Python package index. SkillKit and the projects it generates both require
3.11 (the kit's floor was 3.10 until 0.30.0). No running hub or speaker is needed here.

Start in a working directory where `thalovant-skill-garden-watering` does not
already exist:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --pre "thalovant-skillkit==0.31.1"
thalovant-skillkit new garden-watering
cd thalovant-skill-garden-watering
python -m pip install --pre -e ".[test]" build
thalovant-skillkit check
python -m pytest -q
```

This example pins SkillKit 0.31.1. `--pre` allows the current OVOS prerelease
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

## What the screen shows

A satellite with a display (the Mark II) draws a **card** a skill puts on its
reply, beside the words. A client without a screen ignores it, as one without
alarms ignores the schedule the alarm skills send. The card is data, never
code: four kinds the screen lays out itself, and a layout the skill draws.

```python
from thalovant_skillkit import display

card = display.weather("Toronto", condition="Cloudy", icon="cloudy",
                       temperature=11, high=12, low=4, unit="°",
                       days=[display.item("Wed", "9°", icon="rain")],
                       actions=[display.action("tomorrow", "Tomorrow")])
with display.showing(card):
    self.speak_dialog("weather.answer", {"summary": summary})
```

`display.text`, `display.list_card`, `display.weather` and `display.media`
build the four kinds; `display.showing(card)` attaches it to every reply
spoken inside the block (`speak` and `speak_dialog` keep OVOS's signatures),
and `speak_to(message, text, display=card)` to one. `display.clear()` takes
the cards down. The sizes the satellite enforces are checked here first, so
a card that will not be shown raises `CardError` with the reason.

**A layout of your own.** Ship `gui/thalovant/<name>.rfwtxt`, a Remote
Flutter Widgets file composed from the screen's widget library (`Title`,
`Body`, `Figure`, `Tile`, `Pill`, `Symbol`, `Button`...; the screen's README
lists it), bind the card's `data`, and name the actions its buttons send:

```python
layout = display.layout_file(self, "weather.day")
card = display.layout(layout, data={"place": "Toronto", "temperature": "11"},
                      body=summary, actions=[display.action("refresh", "Refresh")])
```

The file travels with every card, with its hash; a screen that
cannot draw it shows `body`, the words that were said. `display.layout(...,
fullscreen=True)` gives the layout the whole screen, with no frame and no
time along the top: for a card that is a scene of its own, such as a
thank-you mosaic; an ordinary card keeps its frame.

**When a button is tapped**, the satellite reports it as
`thalovant.display.action`; `self.add_display_action_handler(handler)`
delivers `handler(tap, message)` for this skill's cards (`display.Tap`:
`card`, `action`, `skill`, `at`). Answer with `speak_to(message, ...,
display=...)`, so the reply reaches the screen that was tapped. The
contract, with every size, is in thalovant-voice's README, "What the screen
shows".

## A date for ears and for a screen

A reminder read aloud says "tomorrow at nine forty a.m."; the same reminder in
an app reads "tomorrow at 9:40 AM", and one further off "Monday, 28th at
9:40 AM". `moments` gives both forms, and `speak_with_written` sends both, so
a speaker hears one and a screen shows the other:

```python
from thalovant_skillkit.moments import date_text, speak_with_written, time_text, uses_24_hour_clock

clock = uses_24_hour_clock(lang)
spoken = f"Reminder set for {date_text(due, lang, now)} at {time_text(due, lang, clock)}."
written = (f"Reminder set for {date_text(due, lang, now, written=True)} "
           f"at {time_text(due, lang, clock, written=True)}.")
speak_with_written(self, spoken, message, lang, written=written)
```

`duration_text(seconds, lang)` says "five minutes" and writes "5:00". Nothing
is imported until the first date is formatted, so a skill that never says one
pays nothing at boot.

## While the knowledge service looks

A question put to the knowledge service takes a few seconds, and the room is
silent for all of it. Open a `lookup_notice` where you have the message to
answer, and `knowledge_reply` says "From Wikipedia…" the moment the service
names its source and a slow step follows, or "Looking it up…" when nothing has
come back after 1.2 seconds. A quick answer says nothing first:

```python
from thalovant_skillkit.knowledge import knowledge_reply, lookup_notice

with lookup_notice(lambda line: self.speak_to(message, line)):
    reply = knowledge_reply(service_url=url, prompt=question, lang=lang, mode="answer",
                            max_sources=3, augmentation="auto", age_policy_setting=None,
                            headers=headers, timeout=4.0)
```

The line exists in each of the eleven languages the public hubs serve. A skill
that posts its own request calls `ask_service(...)` inside the block instead of
`requests.post`, and gets the same notice.

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
