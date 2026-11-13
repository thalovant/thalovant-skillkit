<!-- Last Edit: Claude Code (Claude Sonnet 5.5) - 2026-11-13 - Motive: 0.37.0 documents `device` (the router's stamp as the only identity) and `safety` (speakable, url_problem), and the guard for a kit before 0.37. -->

# SkillKit reference

Practical contracts for the released Python API and CLI. Start with the
[README](../README.md) for installation, [Writing a Skill](https://docs.thalovant.com/developers/writing-a-skill/)
for base-class choice, or the [SkillKit tutorial](https://docs.thalovant.com/developers/skillkit-tutorial/)
for a complete skill. Source links below contain the full signatures. OVOS owns
intent dispatch, session identity, speech, playback, scheduling and lifecycle hooks.

## Tested OVOS environments

Use `pip install --pre thalovant-skillkit` for the current OVOS prerelease stack.
The fleet also tests Workshop 8 separately with `ovos-workshop==8.0.0` and
`setuptools<81`: its older OVOS Plugin Manager imports `pkg_resources`, which
setuptools 81 removed. This is an upstream legacy dependency constraint, not a
requirement for current OVOS or the artifact checker. Use a separate environment
when testing that combination.

## Messages and text

Import these helpers from `thalovant_skillkit` or
[`thalovant_skillkit.message`](../thalovant_skillkit/message.py).

| Helper | Result and lookup order |
|---|---|
| `utterance(message)` | First nonblank string in `data.utterance`, `phrase`, `text`, `query`, then `data.utterances`; trimmed, or `""`. |
| `utterances(message)` | All nonblank strings in that order, trimmed and deduplicated. |
| `message_lang(message, fallback="en-US")` | First truthy `data.lang`, `context.lang`, `context.session.lang`, fallback, then `en-US`; standardized language tag. |
| `data_of(message)`, `context_of(message)` | The existing dictionary, or `{}` for a missing/non-dictionary value; not a copy. |
| `session_of(message)` | The existing `context.session` dictionary, or `{}`. Does not create or resolve an OVOS Session. |
| `context_value(message, *keys, default=None)` | For **each key in order**, check context then data. Skip `None`, `""`, `{}` and `[]`; preserve `False` and `0`. |
| `location(message)` | `context.location`, then `data.location`, if the selected value is a dictionary; otherwise `None`. No session/geographic/timezone lookup. |
| `standardize(lang)` | Normalize language tags, preserving supplied region/script where supported; an absent value becomes `en-US`. |

Base classes expose `self.utterance(message)`, `self.lang_of(message)`,
`self.context_of(message)` and `self.location_of(message)`. `lang_of` uses the
skill's language as its fallback. These helpers read messages; they do not
change the originating speaker's language or location.

```python
from thalovant_skillkit import context_value, message_lang, utterance
from thalovant_skillkit.testing import message

msg = message("  bonjour  ", lang="fr-FR",
              context={"session": {"lang": "en-US"}, "enabled": False})
assert utterance(msg) == "bonjour"
assert message_lang(msg) == "fr-FR"
msg.data["lang"] = "pt-BR"
assert message_lang(msg) == "pt-BR"
assert context_value(msg, "enabled", default=True) is False
```

[`text.py`](../thalovant_skillkit/text.py) supplies `fold`, `fold_spaces`,
`fold_tight`, `fold_words` and `strip_accents`. An accent goes (Latin,
Greek and Cyrillic diacritics, Arabic harakat, Hebrew niqqud); a mark that
spells a letter stays (the Brahmic and South-East Asian scripts, the kana
voicing marks), except the nukta. A pattern over folded text says
`text.WORD_CHAR` where it would say `\w`, so a Hindi vowel sign counts as part
of its word. Use
[`contains_term(text, term, lang)`](../thalovant_skillkit/vocab.py) or
`matches_any` for language-aware vocabulary containment. This is not exact
whole-utterance matching: a follow-up handler must still decline unrelated
commands. These low-level matchers do not fold their inputs; normalize text
and terms with `fold` first, or use the folding `SkillResources` wrappers.
Language-specific matching rules live in the library's `locale/`.

## Correlated bus requests

`thalovant_skillkit.bus.wait_for_response(bus, message, reply_type, *, matches,
timeout=5.0)` subscribes before emitting and returns the first matching response,
or `None` on timeout. Use it when several rooms share one response topic. Native
topic-only waiters can give both callers the first room's reply.

```python
from uuid import uuid4
from ovos_bus_client.message import Message
from thalovant_skillkit.bus import wait_for_response

# The provider must copy data.id to the reply. This is a protocol requirement,
# not something the helper can arrange on behalf of a different service.
def ask(bus):
    request_id = uuid4().hex
    request = Message("example.query", {"id": request_id},
                      {"session": {"session_id": "kitchen", "lang": "en-US"}})
    return wait_for_response(
        bus, request, "example.answer",
        matches=lambda reply: reply.data.get("id") == request_id,
        timeout=3.0,
    )
```

The predicate must be cheap and should reject malformed replies. Match a fresh
ID for every request, never only a persona, node or session ID. A provider using
`message.reply` can also echo a context correlation field. Confirm the provider's
actual reply contract before selecting a field. Preserve the originating session
when constructing a request; the helper does not modify context or validate the
response payload.

Timeouts must be positive and finite. The deadline includes time spent emitting;
the helper cannot interrupt a blocking transport's `emit`. Unrelated replies do
not extend the deadline. It removes its listener on every exit and propagates
transport and predicate errors to the caller. Handle them with the skill's normal
unavailable response. This helper uses the base dependencies; OvoScope is optional.

## Locale resources and base helpers

Create `SkillResources(locale_dir, default_lang="en-US")`, or use
`self.locale_resources` on a SkillKit base. The base finds `locale/` beside the
skill class, walking its class hierarchy; `LOCALE_DIR` overrides discovery.
See [locale.py](../thalovant_skillkit/locale.py) and
[skill.py](../thalovant_skillkit/skill.py).

Base flags `REQUIRES_NETWORK`, `REQUIRES_INTERNET` and `REQUIRES_GUI` default to
`False`. Each sets the corresponding `*_before_load` and `requires_*` values in
native `runtime_requirements`, with the inverse `no_*_fallback` value. For a skill that loads offline but uses the internet later, set
`REQUIRES_INTERNET=True`, `INTERNET_BEFORE_LOAD=False` and
`NO_INTERNET_FALLBACK=True`. The analogous `NETWORK_*` and `GUI_*` flags work the
same way. Optional flags default to `None`, preserving the original coupled
behavior. Override the property only for a contract the flags cannot describe.
`ThalovantCommonPlaySkill` is `None` when the installed workshop cannot provide
its upstream Open Common Play base.

Language selection prefers an exact tag, then a parent tag, then the language's
reference locale, then other compatible regional resources. The configured
default (normally `en-US`) is the last resort. For example, `en-GB` uses `en-US`
when no British translation is bundled; a partial `fr-CA` folder inherits missing
files from `fr-FR` before English. A matching configured default takes precedence
over the reference variety. OVOS language distance and CLDR data provide the
language/script relationships; there is no fixed list of accepted countries.

Resource fallback never rewrites the message/session language. `en-CA` remains
`en-CA` for speech and routing even when its text comes from `en-US`. Exact regional
files override defaults without copying a whole translation. Incompatible scripts
are not substituted: a `zh-CN` translation alone does not provide Traditional
Chinese support. A missing compatible translation uses the configured default;
fallback is not a claim of a new translation or an available ASR/TTS voice.

| Resource operation | Behavior |
|---|---|
| `available_langs()` | Sorted directory names under the locale root. |
| `lang(lang)` | Resolve and cache the language choice. |
| `matching_langs(lang)` | Ordered compatible bundled locales, without an unrelated default. |
| `candidate_langs(lang)` | Compatible locales, then configured default, without duplicates. |
| `lines(lang, folder, filename, fallback=False)` | Cached tuple of stripped, nonblank, non-comment lines. Always resolves language; `fallback=True` tries the remaining compatible locales before the default when the file has no usable lines. |
| `combined_lines(lang, folder, filename, include_regions=True, unique=False)` | Additive union in candidate order, including the default. Use for aliases or blocklists, not spoken dialogs. `include_regions=False` uses only the resolved locale and default; `unique=True` removes case-insensitive duplicates. Cached results are immutable, instance-local and capped at 512 entries. |
| `vocab(voc_name, lang)` | Lines from `vocab/<name>.voc`, without secondary file fallback. |
| `dialog_lines(name, lang)` | Lines from `dialog/<name>.dialog`, with regional, same-language and default fallback. |
| `dialog_twins(name, lang)` | `dialog_lines`, and the lines of `<name>.ssml` from the same locale (or `None`). |
| `has_ssml(name)` | Whether any locale has `dialog/<name>.ssml`; cached. |
| `matches_literal_intent(utterance, name, lang=None)` | Entire concrete `.intent` line, normalized for case, accents, punctuation and spaces. Reads flat and `intents/` layouts across compatible regional locales. Skips lines with `{}` slots or `[]()\|` patterns. Does not merge English into another supported locale or replace the intent engines. |
| `voc_match(voc_name, utterance, lang=None)` | Containment match against compatible regional then default vocabulary; returns a boolean. |
| `voc_term(voc_name, utterance, lang=None)` | Longest matching folded term in the first matching candidate locale, or `""`. |
| `voc_match_lang(voc_name, utterance, lang=None)` | Candidate locale whose vocabulary matched, or `""`. |

Caches belong to each `SkillResources` instance. Missing files are cached too;
call `clear_cache()` between turns after changing locale files or installing
overrides in place. It clears cached language choices and all resource results.
There is no file watcher or automatic per-request filesystem scan.

A table a skill parses itself -- `canonical|alias|another alias` per line --
lives in `locale/<lang>/tables/<name>.table`, read with
`combined_lines(lang, "tables", "<name>.table")`. It must not be a `.voc`: OVOS
expands every `.voc` under the locale tree by OVOS-INTENT-1, where a `|` outside
`(a|b)` is an error, and from ovos-spec-tools 1.14 one such line stops the skill
loading. The locale check reports any `.voc` line that has one.

Table checks flag aliases that appear to contain a whole list or accidental
repetition. Numbers such as `11` are valid. If a language naturally repeats a
word or syllable, document the reason and exempt only that exact alias in its
`.table` file:

```text
# Swahili: sasa is one word meaning now.
# skillkit: literal-alias sasa
now|sasa
```

The exception is case-insensitive and local to this file. Other aliases still
undergo validation; fix a joined list by separating its terms with `|`.

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from thalovant_skillkit import SkillResources

with TemporaryDirectory() as directory:
    root = Path(directory)
    for lang in ("en-US", "fr-FR"):
        (root / lang / "dialog").mkdir(parents=True)
    (root / "en-US/dialog/hello.dialog").write_text("Hello {name}!\n", encoding="utf-8")
    resources = SkillResources(root)
    assert resources.lang("fr-CA") == "fr-FR"
    assert resources.lines("fr-CA", "dialog", "hello.dialog") == ()
    assert resources.dialog("hello", "fr-CA", {"name": "Sam"}) == "Hello Sam!"
```

`self.mentions(utterance, voc_name, lang=None)` and
`self.mentioned_term(utterance, voc_name, lang=None)` wrap the resource matcher.
Their argument order differs from `SkillResources.voc_match`. Native
`self.voc_match` and `self.resources` remain OVOS APIs.

`self.dialog(name, lang=None, data=None)` returns text: it chooses a random
line, formats `{placeholders}`, and expands literal `\n`. Choices can repeat.
When the dialog has a `.ssml` twin, or a value is marked up, the text is a
`Speech` that also carries the SSML (see [Speech markup](#speech-markup)).
Missing files return the dialog name; missing arguments or malformed formatting
return the raw chosen template. In contrast, `SkillResources.dialog` chooses
the **first** line, does not expand literal `\n`, and catches only missing
format arguments (`KeyError`/`IndexError`), not malformed braces (`ValueError`).
Use native `self.speak_dialog` for OVOS's speech renderer and delivery behavior.

`self.speak_to(message, text, *, lang=None, expect_response=False, written=None,
meta=None, wait=False, display=None)` speaks `text` to whoever sent `message`: it forwards that message,
so the reply keeps its session, source and destination, and speaks in the
message's language unless `lang` is given. It uses the topic the installed
workshop's own `speak` uses (`ovos.utterance.speak` on workshop 9, legacy `speak`
on workshop 8) and stamps `skill_id` into the context. It returns the emitted
message, or `None` for empty text, and raises `RuntimeError` on a skill with no
bus. The topic is found once per process by calling the installed
`OVOSSkill.speak` on a stand-in skill whose bus only records, so it is whatever
that workshop's own `speak` emits; hubs run `OVOS_BUS_EMIT_LEGACY=false`, so
nothing mirrors one topic onto the other. Use it from `converse()`, stop hooks and any handler that answers a room
other than the one `self.lang` describes; `self.speak` remains the native call
for a handler answering the message it was handed. `speech.speak_to(skill,
message, text, ...)` is the same function for skills on other bases. `wait`
blocks as `speak(wait=...)` does: `True` for up to 15 seconds, a number for that
many seconds. A `Speech` sends its SSML as `utterance_ssml`. `written` is the
form a screen shows (see [Dates and clocks](#dates-and-clocks)) and `display` a
card for a satellite with a screen (see [What the screen shows](#what-the-screen-shows)).

`self.setting(key, default=None)` returns the default for unreadable settings,
missing keys or a stored `None`. `False`, `0` and `""` are retained.
`preview_reply(utterance="", lang=None, context=None)` calls your text-only
`reply`; it returns `""` for an empty answer or `NotImplementedError`. It does
not replay a skill's audio or simulate its intent handler.

## Speech markup

A speak message keeps `utterance` as plain words and may carry `utterance_ssml`
beside it: a `<speak>` document that says the same words with markup. Clients
that do not read it ignore it. The Android app and the Kotlin SDK show and say
`utterance` as written, so SkillKit never puts a tag there. The field travels on
whichever topic the workshop speaks on, and the bus's legacy `speak` mirror
copies it. Import the helpers from
[`thalovant_skillkit.ssml`](../thalovant_skillkit/ssml.py).

### Twins

`locale/<lang>/dialog/<name>.ssml` is the SSML twin of `<name>.dialog`. Line N
of the twin goes with line N of the dialog; blank lines and `#` comments are
skipped in both. Each line uses the same `{placeholders}` and says the same
words. Values are escaped in the SSML and left as they are in the plain line.

A twin is optional in every locale. A locale without one says its plain line,
and a twin is never borrowed from another locale. A region in `regional.json`
that rewords a dialog without also giving its twin gets no twin for it.

`speak_dialog`, `speak_varied_dialog` and `dialog` draw one line and render both
forms from it. The fallback base speaks what `reply` returns, twin included.
A skill that picks its own line can use `SkillResources.dialog_twins(name, lang)`,
which returns the lines and the twin's lines from the same locale, and
`ssml.render_line(plain, twin, data)`.

The twin is left out, and OVOS renders the dialog exactly as before, when:

- OVOS would render other lines than the skill's own, such as an operator's
  override or a different language;
- the dialog uses `(a|b)` or `[optional]`, which OVOS expands at random;
- a `render_callback` changes the words;
- the twin's line count differs from the dialog's, or a filled-in line does not
  parse. That is logged once.

### Pacing every line without twins: `SPEECH_STYLE`

A skill that only wants its replies paced (a pause after each sentence, after a
colon or a dash, a slower rate) declares it once on the class instead of writing
a twin per dialog per language:

```python
from thalovant_skillkit.ssml import SpeechStyle

class WeatherSkill(ThalovantFallbackSkill):
    SPEECH_STYLE = SpeechStyle(rate="95%", sentence_break="350ms", colon_break="300ms")
```

`speak_dialog` and `dialog()` then send `utterance_ssml` derived from the dialog
line's own words (`ssml.auto_twin(template, style, lang)`): the rules read the
template, never what a `{placeholder}` is filled with, so a value that contains a
full stop is not cut in two, and values are escaped as for any twin. A
hand-written `.ssml` twin still wins for its line. `checks.redundant_twins(root,
style)` lists twins that say nothing the style does not, so a skill's tests can
keep them deleted.

Fields: `rate`, `pitch`, `breaths` (the `auto_breaths` frequency),
`sentence_break`, `colon_break` (also `;`), `dash_break` (`—`, `–`), `comma_break`,
and `say_as` (on by default; see below). Unset fields do nothing; with no
`SPEECH_STYLE` a skill is sent exactly as before.

**Where the pauses go, in every language the skills ship.** A sentence ends at
`.`, `!`, `?` or `…` followed by a space and more words, and also, with no space
needed, at the marks of the scripts that do not write one: `。！？` (Japanese,
Chinese), `।` (Hindi, Bengali), `؟` (Arabic, Persian), `۔`, `։`, `።` and `။`.
`，、` `،` and `；` `؛` `：` are the matching commas, semicolons and colons. No
space is added where the language wrote none. A full stop that is not the end of a
sentence gets no pause: after a title (`Dr.`, `Mr.`, `M.`, `Mme`, `Sra.`, `St.`), an
initial (`J. R. Smith`), a dotted abbreviation or a month, day or `no.` when a
lower-case word or a number follows (`9 a.m. on Monday`, `Nov. 9`), and after a
number in the languages that write an ordinal that way (`am 9. November`: German,
Czech, Danish, Norwegian, Finnish, Hungarian and others). A spaced en dash between
two numbers is a range (`9 – 5`), not a pause. These are heuristics, read from the
template alone: a line that must be paced differently gets a `.ssml` twin.

**Numbers, times, dates, amounts and units.** A literal `14 h 30`, `3,50 €` or
`23 °C` in a dialog is read by the voice's own text normalizer, which says
"quatorze h trente", "trois virgule cinq euros" and "un deux cents" for `1 200`.
With `say_as` on and the line's language in `ssml.SAY_AS_LANGUAGES` (English,
French, German, Spanish, Italian, Portuguese, Dutch: the languages phoonnx has word
tables for), the kit wraps what it can read unambiguously in `<say-as>`, and the
voice reads it with the language's own rules:

| In the dialog | Wrapped as | Examples |
|---|---|---|
| A clock | `time` | `7:30 pm`, `14:30`, `14 h 30`, `14h30` (not a bare `9 am` or `9 h`) |
| A numeric date | `date` | `2026-11-09`, `11/09/2026`, `09.11.2026` (the order follows the language) |
| An amount | `currency` | `$12.50`, `3,50 €`, `12,99 $`, `£4.20`, `5 EUR` |
| A quantity | `unit` | `23°C`, `23 °C`, `15 km/h`, `5 km`, `10 %`, and a placeholder before `%` or `°C`: `{chance}%` |
| An ordinal | `ordinal` | `3rd`, `21st` in English; `1er`, `2e`, `3ème` in French |
| Thousands | `cardinal` | `1,200` in English; `1 200` with a no-break space elsewhere |

A French comma is a decimal mark, so `1,200` is left alone there; a placeholder
is wrapped only when it stands directly before `%` or a degree sign, since its value
is unknown; and a language outside the list, or no language at all, gets the
pauses only. The plain words never change: the wrapped text is the written text.
`SpeechStyle(say_as=False)` turns it off. A value that arrives at run time is
wrapped by the skill itself: `self.speak_dialog("ready", {"time": ssml.as_time(value)})`.

Why `.ssml` and not `.ssml.dialog`: OVOS reads every `.dialog` file as a plain
template in which `<name>` names a vocabulary. It would load
`joke.ssml.dialog` as a dialog called `joke.ssml` and raise on the first
`<break/>`, and `ovos-spec-lint` reports it. OVOS ignores a `.ssml` file.

### Older kits: guard what you import

A hub installs a new skill release by itself, but the running `ovos-core` keeps
the SkillKit it imported at boot until the pod restarts. A skill whose module does
`from thalovant_skillkit.ssml import SpeechStyle` against a kit from before 0.34
then raises `ImportError` while it loads, and the whole skill stops answering (the
weather skill was gone for twelve hours that way). Any name a skill uses that is
newer than its kit floor is a nicety, and a nicety is imported behind a guard. Keep
the floor in `requirements.txt` as it is, and use one of these.

Anywhere, on every kit, with nothing from SkillKit's newer modules:

```python
try:
    from thalovant_skillkit.ssml import SpeechStyle
except ImportError:  # a kit before 0.34, still loaded on a hub that upgraded in place
    SpeechStyle = None


class GardenSkill(ThalovantFallbackSkill):
    SPEECH_STYLE = SpeechStyle(sentence_break="350ms") if SpeechStyle else None
```

From kit 0.36, `thalovant_skillkit.compat` does the lookup for you. It imports nothing
that may be missing: each function asks the kit that is *loaded*, so it also works when
the files on disk are newer than the kit in memory, which is what an in-place upgrade
leaves.

| Function | Returns |
|---|---|
| `speech_style_or_none(**fields)` | `ssml.SpeechStyle(**fields)`, or `None` when the loaded kit has no `SpeechStyle`. A field the loaded kit does not know is left out (logged at debug level); a value no voice reads is still a `ValueError`. |
| `ssml_helper(name)` | The kit's `ssml.<name>` helper, or a stand-in that takes the same arguments and returns the plain words as a `str` (nothing for `pause`, `mark` and `breath`). A name that is not an `ssml` helper at all raises `ValueError`, so a typo is not taken for an old kit. |
| `kit_attr(module, name, default=None)` | `thalovant_skillkit.<module>.<name>`, or `default` |
| `kit_version()`, `kit_at_least("0.34")` | The loaded version as a tuple, and whether it is at least that |

```python
from thalovant_skillkit.compat import speech_style_or_none, ssml_helper

cardinal = ssml_helper("cardinal")  # the kit's helper, or the text as written


class GardenSkill(ThalovantFallbackSkill):
    SPEECH_STYLE = speech_style_or_none(rate="95%", sentence_break="350ms")

    def tell_total(self, total):
        self.speak_dialog("count", {"total": cardinal(f"{total:,}")})
```

A kit older than 0.36 has no `compat`, so a skill that still supports one imports
`compat` behind the same `try`/`except ImportError`, or uses the plain guard above.
The skill's tests should run once against its kit floor (a virtualenv with
`thalovant-skillkit==<floor>`): `import` is where this fails, and nothing else
catches it.

### Markup from Python

Each helper returns a `Speech`: a `str` whose text is the plain words, with the
markup in `.ssml` (a fragment, or `None`) and `.document` (for `utterance_ssml`).
It goes wherever a string goes. `+` keeps the markup on either side; f-strings,
`str.format` and string methods return a plain `str` without it.

| Helper | SSML | Plain words |
|---|---|---|
| `say(*parts, sep=" ")` | Parts joined; a plain string is escaped | Parts joined |
| `pause("1s")`, `pause("750ms")`, `pause(strength="strong")`, `pause()` | `<break>` | Nothing |
| `spell(text)` | `<say-as interpret-as="characters">` | `text` |
| `digits(text)`, `telephone(text)` | `<say-as interpret-as="digits">`, `"telephone"` | `text` |
| `foreign(text, "fr-FR")` | `<lang xml:lang="fr-FR">` | `text` |
| `emphasis(text, level="moderate")` | `<emphasis>` | `text` |
| `sub(written, spoken)` | `<sub alias="spoken">written</sub>` | `spoken` |
| `cardinal(text)`, `ordinal(text)`, `fraction(text)`, `unit(text)`, `currency(text)`, `address(text)` | `<say-as interpret-as="cardinal">`, `"ordinal"`, `"fraction"`, `"unit"`, `"currency"`, `"address"` | `text` |
| `as_date(text, format=None)`, `as_time(text, format=None)` | `<say-as interpret-as="date">`, `"time"` (`format="mdy"`, `"hms24"`) | `text` |
| `interjection(text)`, `expletive(text)` | `<say-as interpret-as="interjection">`, `"expletive"` (a bleep) | `text` |
| `phoneme(text, ph, alphabet="ipa")` | `<phoneme>`, IPA or `"x-sampa"` | `text` |
| `prosody(text, rate=, pitch=, volume=)`, `pitch(text, "+2st")` | `<prosody>` | `text` |
| `whisper(text)`, `soft(text)`, `compress(text)`, `vocal_tract(text, "+20%")` | `<amazon:effect>` (`name="whispered"`, `phonation="soft"`, `name="drc"`, `vocal-tract-length`) | `text` |
| `auto_breaths(text, frequency="medium")`, `breath("short")` | `<amazon:auto-breaths>`, `<amazon:breath/>` | `text`, nothing |
| `mark("name")` | `<mark name>`: the voice reports when its audio reaches it | Nothing |
| `markup(template, **values)` | The template, values escaped | Read from the SSML |

A `Speech` passed as a dialog value marks up that value even when the dialog has
no twin: the SSML is the plain line, escaped, with the value's markup in place.
`self.speak_dialog("code", {"code": spell(code)})` works in every language.

`markup` is for SSML written in the skill's own code. Its values are escaped, and
a `Speech` value keeps its markup. It raises `ValueError` for markup a voice does
not read. Never pass text from a user or a service as the template.

`pause` refuses a number without a unit, since SSML has none by default.

### The plain words

When the plain words are read out of SSML, `<sub>` gives its alias, since the
plain words are what a client without SSML says aloud. `<say-as>` and
`<phoneme>` keep the text as written: how "XK7" is spelled aloud depends on the
language and the voice, and a screen shows the same words. A `<break>`, `<p>` or
`<s>` becomes a single space. Entities are read.

**A voice without SSML.** `utterance` is always the plain words: no tag, no
`speak`, no entity (`&amp;` is `&`). A TTS that ignores `utterance_ssml` says them
as written, and its own text normalizer reads `5km`, `$12.50` or `7:30 pm` as best
it can. What it says for each helper:

| Helper | Said without SSML |
|---|---|
| `spell`, `digits`, `telephone`, `cardinal`, `ordinal`, `fraction`, `unit`, `currency`, `address`, `as_date`, `as_time`, `interjection` | The text as written |
| `emphasis`, `prosody`, `pitch`, `whisper`, `soft`, `compress`, `vocal_tract`, `auto_breaths`, `foreign`, `phoneme` | The text as written, in the voice's own tone, language and pronunciation |
| `sub(written, spoken)` | The `spoken` words |
| `expletive` | The word itself: it is bleeped only by a voice that reads SSML, so use it where a screen or a plain TTS saying the word is acceptable |
| `pause`, `mark`, `breath` | Nothing |

A skill that wants a time or a date said in words by every client, SSML or not,
writes the words itself: `moments.time_text(value, lang, use_24hour)` and
`moments.date_text(value, lang, now)` return the spoken form.
A voice built on an older phoonnx reads the markup it does not know as the same
plain words, so a skill never needs two code paths.

If a skill passes SSML as a plain string to `speak`, `speak_to` or
`speak_dialog`, the markup is moved to `utterance_ssml`, the plain words are sent
as `utterance`, and a warning is logged once per skill. Markup that does not
parse loses its tags and keeps its words.

### Supported tags

| Tag | Attributes |
|---|---|
| `<speak>` | `xml:lang`, around the whole line only. It is sent as a `<lang>` inside the one `<speak>` the message gets, since SSML forbids nesting. |
| `<break>` | `time` (`500ms`, `1s`, at most 10 seconds) or `strength` |
| `<p>`, `<s>` | none |
| `<prosody>` | `rate` (named or a percentage), `volume` (named or dB), `pitch` (named, `+2st` or a percentage; Hz is not rendered) |
| `<emphasis>` | `level`: `strong`, `moderate`, `reduced` or `none` |
| `<lang>`, `<voice>` | `xml:lang` |
| `<say-as>` | `interpret-as`: `characters`, `spell-out`, `digits`, `telephone`, `cardinal`, `number`, `ordinal`, `fraction`, `unit`, `date` (`format` such as `mdy`), `time` (`format` `hms12` or `hms24`), `currency`, `address`, `expletive`, `interjection`, `letters` or `verbatim` (the last two read like `characters`). `format` belongs to `date` and `time` only |
| `<sub>` | `alias` |
| `<w>` | `role`; the words are read as they are |
| `<phoneme>` | `ph`, and `alphabet="ipa"` or `"x-sampa"`. `ph` must not contain `[[` or `]]`. X-SAMPA writes `{` for "æ": in a `.ssml` twin or a `markup()` template write `{{`, as in any format string |
| `<mark>` | `name` |
| `<amazon:effect>` | `name` (`whispered`, `drc`), `phonation="soft"`, `vocal-tract-length` (a percentage) |
| `<amazon:auto-breaths>` | `frequency`, `duration`, `volume` |
| `<amazon:breath>` | `duration`, `volume` |
| `<amazon:domain>` | `name`; the words are read as they are |

Thalovant voices read `<audio>` and any other prefixed tag as plain words (an
`<audio src>` is never fetched), so the check reports them. Pitch, whisper, soft, compression, breaths and bleeps are
applied to the finished audio and need a voice built on phoonnx with SSML support
(phoonnx PR #539); on an older voice they are read as plain words. Emotions and
speaking styles are not something these voices do.

### What the check reports

`check_ssml(skill_root)` is part of `check_all` and runs under both
`thalovant-skillkit check` and `check --fleet-only`. Every error fails the check:

- a plain `.dialog` line that holds an SSML tag;
- a `.ssml` file with no `.dialog` beside it, or a different number of lines;
- a twin line that is not well-formed XML, or uses an unsupported tag,
  attribute or value, each named: a `<break>` without a unit, with a negative
  time or one over ten seconds; a `<prosody>` with nothing to change; a
  `<say-as>` with an unknown `interpret-as`, a `format` that is not a date order or
  `hms12`/`hms24`, or a `format` on anything but a date or a time; a `<phoneme>`
  with no or an empty `ph`, or one holding `[[`;
- a twin line whose `{placeholders}` differ from its plain line;
- `(a|b)` or `[optional]` in a dialog that has a twin;
- a twin line that does not say the same words as its plain line. Punctuation,
  case and accents are ignored, and a `<sub>` may match either form.

A skill without `.ssml` files and without tags in its dialogs passes unchanged.

### Testing

`testing.FakeBus.spoken_ssml()` and `testing_ovos.CapturedTurn.spoken_ssml`
return the `utterance_ssml` of each sentence, in the same order as `spoken`, with
`None` for a sentence sent without markup.

```python
from thalovant_skillkit.ssml import pause, say, spell

joke = say("Why?", pause("1s"), "Because.")
assert joke == "Why? Because."
assert joke.document == '<speak>Why? <break time="1s"/> Because.</speak>'
assert spell("XK7").ssml == '<say-as interpret-as="characters">XK7</say-as>'
```

## Dates and clocks

[`thalovant_skillkit.moments`](../thalovant_skillkit/moments.py) says a date, a
clock or a duration the way a voice should, and writes it the way a screen
should: the two forms travel together as `utterance` and `utterance_written`.
`ovos-date-parser` and `babel` are imported on the first call, never at import.

| Helper | Spoken (default) | Written (`written=True`) |
|---|---|---|
| `uses_24_hour_clock(lang)` | Whether the locale writes `19:30` or `7:30 PM`, from CLDR's short time pattern; `False` for an unknown locale. | |
| `time_text(value, lang, use_24hour, *, written=False, rules=None)` | "nine forty a.m.", "midnight" | `9:40 AM` or `21:40`; `rules` (a locale's own `time_pattern`, `time_pattern_24`, `am`, `pm`) win, the marker substituted in place, and CLDR's short clock is used only when it keeps the asked-for cycle. |
| `date_text(value, lang, now, *, written=False, rules=None, plain=False, relative=True)` | "tomorrow", "Monday the twenty-eighth" | "today"/"tomorrow" kept; otherwise `EEEE, d` ("Monday, 28th" in English) or the locale's `date_pattern` / `date_pattern_plain`; `relative=False` always gives the concrete date. Never the empty string. |
| `date_time_text(value, lang, now, *, written=False)` | Day and clock through upstream's per-language template | The same, written; CLDR's medium format for a language upstream has no template for. |
| `duration_text(seconds, lang, *, written=False)` | "five minutes" | `5:00`, `1:02:03` |
| `tidy_sentence(text)` | Collapses the doubled full stop a spoken "a.m." leaves before a sentence's own. | |
| `english_ordinal(day)` | `1st`, `2nd`, `3rd`, `11th`, `12th`, `13th`, `21st` | |

A rule set is a mapping a locale ships (`thalovant-languages` carries them); a
rule that does not apply falls through to the defaults above. Every entry
point falls back rather than raising when a language's upstream resources are
missing: the ISO date or `HH:MM` is the last resort.

`WrittenForms.say(spoken, written)` records a pair as a reply is composed and
returns the spoken half; `WrittenForms.render(reply)` is that reply with every
recorded pair written out, longest first, and the sentence's full stop kept.
Call `WrittenForms.reset()` at the start of a turn; the record is thread-local.
`speak_with_written(skill, reply, message, lang, written=None)` sends the
reply through `speech.speak_to` with `written` as `utterance_written` beside
it: pass the written form yourself, `written=WrittenForms.render(reply)` for
a reply composed through `say`; with `written=None` only the spoken words are
sent, and a screen shows those. It falls back to `skill.speak` on a skill
with no bus.

## What the screen shows

`thalovant_skillkit.display` builds the card a satellite with a display draws
from a reply's `meta["display"]` (the satellite's contract: thalovant-voice,
README "What the screen shows"; the screen's widget library: thalovant-screen,
README).

| Helper | Builds |
|---|---|
| `text(body, *, title, subtitle, identifier, actions, ttl, lang)` | a title and a body |
| `list_card(items, *, title, subtitle, ...)` | up to 12 `item(label, value, icon=, identifier=)` rows, or bare labels |
| `weather(place, *, condition, icon, temperature, high, low, feels_like, unit, wind, humidity, precipitation, days, ...)` | the forecast; numbers are printed as given, `icon` is one of `WEATHER_ICONS` |
| `media(image_bytes, mime, *, title, body, ...)` | a PNG, JPEG or WebP under 512 kB, embedded |
| `layout(layout, *, data, body, actions, image, fullscreen=False, ...)` | the skill's own layout bound to `data` (strict JSON: no `NaN`, at most 16 kB); `body` is shown where it cannot be drawn; `image=(bytes, mime)` is checked as `media` checks one; `fullscreen=True` gives it the whole screen, with no frame and no time along the top |
| `layout_file(skill, name, *, root=None)` | reads `gui/thalovant/<name>.rfwtxt` beside the skill, hashed |
| `action(identifier, label)` | a button; `identifier` comes back in the tap |
| `clear(skill="")` | takes every card down, or one skill's |

`ttl` is seconds (up to a day); `None` keeps the card until it is cleared,
replaced or closed; the default leaves it to the satellite (two minutes). An
`identifier` names the card so a later one replaces it; without one the
satellite uses `<skill_id>:<kind>`. Every size the satellite enforces
(`TITLE_LIMIT`, `TEXT_LIMIT`, `ITEM_LIMIT`, `ACTION_LIMIT`, `MAX_IMAGE_BYTES`,
`MAX_LAYOUT_BYTES`, `MAX_DATA_BYTES`) is checked when the card is built and
raises `CardError` with the reason, as is a figure or a value a screen cannot
print (a non-finite number, or an integer too large for a float). `lang` names
the card's language for the screen's typography; the satellite drops a value
that is not a language tag.

Putting it on a reply: `showing(card)` is a context manager that attaches the
card to every reply spoken inside it, through `speak`, `speak_dialog` and the
kit's helpers alike; `speak_to(message, text, display=card)` and
`speak_varied_dialog(key, display=card)` take one directly. `attach(meta,
card)` returns `meta` with the entry, for a skill that builds its own speak
message. A layout's text is always sent inline, with its `sha256`, since
0.29.1 (0.29.0 sent it once per process, and the satellites that were not the
first to ask got a hash they did not have); `forget_sent_layouts()` remains
as a no-op.

What comes back: a tap on a card's action reaches the hub as
`thalovant.display.action` with `{"card", "action", "skill", "at"}`.
`add_display_action_handler(handler)` on a skill follows the event once and
calls `handler(tap, message)` with a `Tap` (`card`, `action`, `skill`, `at` as
a float) for this skill's cards only: the report's `skill` is this skill's id,
or its `card` starts with `<skill_id>:`. `tap(data)` is the parser, `None` for
a report that cannot be believed: ids that are not plain ids, or an `at` that
is not a finite number.

## Non-repeating choices

Import `ShuffleBag` from
[`thalovant_skillkit.selection`](../thalovant_skillkit/selection.py) when a skill
cycles through sounds, questions or dialog lines. It keeps each equal item once
and draws every item before reshuffling. Adjacent draws differ whenever the pool
has at least two items. An empty input raises `ValueError`; a one-item pool always
returns that item.

```python
from random import Random
from thalovant_skillkit.selection import ShuffleBag

sounds = ShuffleBag(["duck.ogg", "bear.ogg", "robot.ogg"], rng=Random(7))
first = sounds.draw()
assert sounds.draw() != first
# Another speaker may have played in between this speaker's requests.
assert sounds.draw(avoid=first) != first
```

`draw(avoid=item)` replaces the previous-draw rule with the caller's chosen item.
If that item is the only one left in a larger pool, the bag starts a fresh cycle
to avoid repeating it. Each bag owns its history and lock; the skill owns speaker
state, lifetime and compound playback operations. Pass a seeded `random.Random`
for repeatable tests. To vary spoken lines, select through OVOS's public
`speak_dialog` rendering callback so native rendering and message metadata remain
available; the helper itself neither formats nor plays its items.

## Fallback priorities

[`ThalovantFallbackSkill`](../thalovant_skillkit/skill.py) defaults to priority
**100**; the CLI scaffold defaults to **98**. Define a narrow `can_answer`
and return text or `None` from `reply`. `handle_fallback` speaks a truthy reply
to the message it was given (`speak_to`, so the room that asked hears it in its
language) and returns `True`; an empty reply returns `False`. If you override
`initialize`, call `super().initialize()` to retain registration.

[`resolve_priority(settings, default, band=(90, 101))`](../thalovant_skillkit/fallback.py)
reads `fallback_priority`, converts it with `int()`, and accepts only values
strictly between the band endpoints: **91–100** by default. Missing, invalid
or out-of-band overrides return the supplied default, without clamping.
This helper does not validate that the default itself lies in the band;
`check` validates declared fallback priorities separately.

`register_once(skill, handler, priority)` returns whether registration happened.
An already registered handler is left alone, including its existing priority;
calling it again does not move that handler to a new rung.

## Volatile session state

Import `SessionStateStore` explicitly from
[`thalovant_skillkit.sessions`](../thalovant_skillkit/sessions.py). Its constructor
is `SessionStateStore(max_entries, default_ttl=None, clock=time.monotonic)`.
It stores application values under the session IDs your skill supplies.
`max_entries` must be a positive integer; no TTL is applied by default.

| Operation | Contract |
|---|---|
| `store[key] = value`, `store.set(key, value)` | Apply default TTL and move the key to the newest write position. Evict the oldest-written live entry if full. |
| `store.set(key, value, ttl=seconds)` | Override relative TTL for this write. `ttl=None` disables expiry. |
| `store.set(key, value, expires=deadline)` | Absolute deadline in the injected monotonic clock's domain. Cannot be combined with `ttl`. |
| `store[key]`, `get`, `in`, `len` | Observe live entries; reads do not extend TTL or refresh eviction recency. Missing indexing raises `KeyError`. |
| `store.prune()` | Atomically remove currently expired entries and return `{key: value}` for those removals. Earlier lazy removals are not retained for reporting. |
| `store.remove(key, expected=value)` | Remove only if the live value is that exact object (`is`); return a boolean. Omit `expected` for unconditional live removal. |
| `pop`, `popitem`, `del`, `clear` | Dictionary-style removal of stored references. No playback, scheduler or resource cleanup is performed. |
| `keys()`, `values()`, `items()`, iteration | Snapshots of live entries. The values themselves are not copied. |
| `setdefault(key, default=None)` | Atomically preserve a live value or insert the default using the default TTL. |
| `store.lock` | Per-instance reentrant lock for compound operations and mutable values. |

Expiry is lazy, with no timer thread or lifecycle callbacks. TTLs must be
finite and nonnegative; absolute deadlines must be finite. A zero TTL or past
deadline removes that key's old value without evicting another live entry.
In-place value edits do not refresh TTL; call `set` when an accepted turn should
renew it. Turn budgets, anonymous-session policy and resource cancellation
remain the skill's responsibility. Hold `store.lock` across a compound update,
including `update()` when the whole batch must be atomic; keep blocking I/O and
playback waits outside it.

```python
from thalovant_skillkit.sessions import SessionStateStore

now = [0.0]
states = SessionStateStore[dict](max_entries=2, default_ttl=10, clock=lambda: now[0])
old = {"turns": 1}
states["room-a"] = old
states["room-a"] = {"turns": 1}  # Equal contents, different conversation object.
assert not states.remove("room-a", expected=old)
with states.lock:
    state = states["room-a"]
    state["turns"] += 1
    states.set("room-a", state)
now[0] = 10.0
assert states.get("room-a") is None
```

## Test helpers

[`testing.message`](../thalovant_skillkit/testing.py) builds an actual bus
`Message` when available, otherwise a small data/context double. Defaults:
`utterance=""`, `lang="en-US"`, `msg_type="recognizer_loop:utterance"`.
Optional `session`, `location`, `site_id` populate context; an explicit context
key wins over these defaults. Extra keywords populate message data.
`testing.FakeBus` records emissions and registrations; it does **not** dispatch
callbacks or produce replies for `wait_for_response`. `spoken()` and
`spoken_ssml()` read back each sentence and its markup. Use it for small unit
tests, and the following optional helpers for framework integration.

Install with `python -m pip install --pre "thalovant-skillkit[testing]==0.37.0"`;
this selects the OVOScope prerelease test stack. The old `[skill]` and `[fleet]`
extras are empty compatibility
names: their dependencies are already included in the base install.

Import integration helpers from
[`testing_ovos.py`](../thalovant_skillkit/testing_ovos.py). Importing that module
does not itself load OVOS. **Enter XDG isolation before importing tested skills
or OVOS**, since upstream modules can cache environment paths at import time.

| Helper | Defaults, ownership and result |
|---|---|
| `isolated_xdg(root=None)` | Context manager yielding a `Path`; sets four XDG variables and restores previous values. Temporary roots are deleted; an explicit caller-owned root is retained. |
| `skill_harness(skill_type, *, skill_id, settings=None, scheduler=True, scheduler_autostart=False, bus_options=None, **skill_options)` | Yields `SkillHarness(skill, bus, scheduler)`. Constructs upstream dispatching `FakeBus`, isolated settings and, by default, `ScheduledEventService` with no timer thread. Drive its public `tick()` when testing scheduled work. Extra skill options go to the constructor. |
| `managed_minicroft(skill_ids, **options)` | Yields upstream `get_minicroft(...)`; always calls `croft.stop()` on exit. Options such as `default_pipeline` are passed upstream. Does not add XDG isolation. |
| `capture_turn(croft, source, *, timeout=30, **capture_options)` | Runs and finishes upstream `CaptureSession`; raises `AssertionError` on timeout. Capture options such as `eof_msgs`/`terminal_signals` go upstream. Returns `CapturedTurn`. |
| `deferred_capture_gc()` | Applies the scoped finalizer workaround only for exactly OVOScope `1.8.5a1` + pyee `12.1.1`. Other versions retain normal GC behavior. |

The harness shuts down its skill before its scheduler, then closes the bus and
restores its settings-path override. It isolates paths internally, but cannot
undo OVOS imports made before entry. Environment/class-property patches are
process-wide: use separate workers instead of overlapping threaded scopes.
Put `deferred_capture_gc()` outside MiniCroft owners so they stop before its
final collection; do not invoke it inside a bus callback.

`CapturedTurn.messages` is the full captured message list, not a session-filtered
list. `of_type(topic)` selects an exact topic. `spoken` returns canonical
`ovos.utterance.speak` text when present, otherwise legacy `speak` text.
`spoken_ssml` returns the `utterance_ssml` of the same messages, `None` where absent.
`session` is the latest captured carrier matching the source's declared session
ID, deserialized to an OVOS Session; it is `None` when the source declares no ID.
Completion alone does not prove correct routing, replies or session isolation:
assert those outcomes in your test.

`turn.for_session(session_id)` returns a view containing only messages with that
explicit session ID. Filter first, then use `spoken`, `audio` or `audio_stops` to
assert the intended room's output. `audio` returns decoded remote bytes and their
extension, or a local URI, with the original message for routing checks. It never
opens or plays a URI. Malformed audio payloads raise `AssertionError`.
See [per-speaker speech and audio assertions](testing-audio.md) for examples,
namespace handling, and the distinction between queued output and audible sound.

## Source and fleet checks

[`check_all(source_root)`](../thalovant_skillkit/checks.py) returns a list of
problems, empty on success. It checks entry-point/class declarations with AST,
package-data declarations with a text heuristic, fallback priority and the
locale contract. It does
not import an installed plugin or inspect a built wheel. Discovery expects a
root-level `thalovant_skill_*` package.

The locale baseline is `en-US`, with supported locales listed in
`locale/supported.json`. Checks cover missing baseline resources, JSON and regex
syntax and shared technical metadata. Placeholder **sets**, not occurrence
counts, must match; `fr-FR` retains the existing placeholder-parity exemption.
Passing these checks does not establish translation quality or intent accuracy.

`check_intent_templates(source_root)` reads every `.intent` line under every
locale directory, listed in `supported.json` or not, the way OVOS reads it: as
an OVOS-INTENT-1 template, expanded by ovos-spec-tools. `(a|b)` is a choice,
`[x]` and `[a|b]` are optional, `<name>` stands for the lines of `<name>.voc`
anywhere under that language's directory, and `{name}` is a slot. OVOS skips a
line it cannot expand, with a log line and nothing else, so each of these is an
error naming `file:line` and what to write instead: brackets that do not pair,
a line that is only a `{slot}`, a `<name>` with no `.voc` in that language, a
`|` outside a group, two slots with no word between them. The check runs under
`check` and `check --fleet-only`. The fleet comparison expands lines the same
way, through `intents.expand`, and a line OVOS skips publishes no sentence.

| CLI option | Effect |
|---|---|
| `check [directory]` | Local contracts plus the default published fleet model when the skill has intents. Directory defaults to the current directory. |
| `--no-fleet` | Disable the published model. Without `--fleet`, only local contracts run. |
| `--fleet-only` | Skip local contracts, except the [speech markup check](#what-the-check-reports) and the intent template check; incompatible with `--no-fleet`. |
| `--model ID\|DIR` | Override `thalovant/thalovant-m2v-intents` with a Hub model or local model directory. |
| `--fleet DIR` | Add corpus files `<lang>.json`; report source lines and near paraphrases. The model comparison still runs unless disabled. |
| `--no-near`, `--threshold 0.85` | Disable corpus paraphrase comparison, or set its similarity threshold. These do not disable/configure the trained classifier comparison. |

For an offline corpus-only comparison, combine `--fleet DIR --no-fleet --no-near`.
Missing corpus languages and skipped comparisons appear as notes. Read them.
New blocking duplicate claims fail; model predictions, close paraphrases and
already-published collisions are reported for review. A `ModelUnavailable`
failure is a visible local skip but fails when `GITHUB_ACTIONS` is set.

CLI results: `0` means no blocking problems, `1` means checks failed, and `2`
means invalid usage. Local offline skips can therefore return `0`.
`new NAME [--directory DIR] [--priority 98]` accepts priorities 91–100 and
refuses to overwrite a nonempty directory (exit `2`). See
[cli.py](../thalovant_skillkit/cli.py) for complete arguments.

## Built-artifact checks

[`check_artifacts(source_root, *, wheel=None, sdist=None, ...)`](../thalovant_skillkit/artifacts.py)
returns problem strings. At least one archive is required. It compares declared
files by SHA-256, checks archive paths/member types/duplicates and basic package
metadata, and requires wheel/sdist package names and versions to agree when
both are supplied. It does not build, extract, install, import or fetch anything.

| CLI option | Meaning |
|---|---|
| `check-artifacts [directory] --wheel PATH --sdist PATH` | Validate one or both existing archives against the source checkout. |
| `--package DIR` | Repeatable import-package directory. Omission discovers the first root-level `thalovant_skill_*`; use explicit `--package src/package_name` for a src layout. |
| `--runtime PATH` | Additional source-relative file/directory required in both supplied artifacts at that relative path. |
| `--source PATH` | Additional source-relative file/directory required only in the supplied sdist, such as regeneration inputs. |
| `--wheel-exclude PATH\|GLOB` | Reject matching wheel files, exact paths or directory prefixes. Repeatable. |
| `--wheel-count 'GLOB=N'`, `--sdist-count 'GLOB=N'` | Exact inventory counts; quote globs so the shell does not expand them. Repeatable; count must be nonnegative. |

All files below declared package directories are expected, except supported
interpreter/tool caches. Wheel paths start with the package directory's name;
sdist paths retain `src/` where applicable. Declared source paths must stay
inside the source root; symlinks are rejected. The validator does not reject
every undeclared extra file: use exclusions/counts for additional policy.
Basic metadata checks do not verify every RECORD hash or wheel-filename field.
Follow this with an installed-plugin smoke test outside the source checkout.
Exit codes are `0` for success, `1` for validation failures, `2` for invalid CLI
arguments, including omitting both archives.

## Service and knowledge clients

[`request_headers(skill_name, skill_version, user_agent, *, url=None)`](../thalovant_skillkit/service.py)
sets User-Agent, a fresh X-Request-ID, skill name and version headers. With
`url`, it also sets the runtime's service token when `url` is one of the
platform's services (see [The service token](#the-service-token)); without
`url`, or for any other host, it supplies no credential.

`post_json(url, payload, *, headers=None, timeout=2.4, attempts=2, client=requests)`
returns `response.json()` or `None` after failure. It makes at least one attempt,
returns immediately for HTTP 4xx (including 429), and retries connection errors,
HTTP 5xx and unusable JSON up to the attempt limit without backoff. Timeout is
passed to each request; it is not a total wall-clock deadline. The decoded JSON
is **not validated as a dictionary**, despite the return annotation. Validate
the response your skill requires; `None` can also be a decoded JSON null.
It sends the service token to the platform's services and drops one the kit
set for any other URL; a 401 from a service is asked once more, outside the
attempt count, only when the token file then holds a different token.

### The service token

[`service_auth`](../thalovant_skillkit/service_auth.py) reads the runtime
group's token from the file named by `THALOVANT_SERVICE_TOKEN_FILE` (in a
platform runtime, `/home/ovos/.config/thalovant/service-token/token`) and sends
it as `Authorization: Bearer <token>`, only to these hosts, over http or https:
`<service>.thalovant`, `<service>.thalovant.svc` and
`<service>.thalovant.svc.cluster.local` for `thalovant-llm`,
`thalovant-embedder`, `thalovant-knowledge-service`,
`thalovant-weather-service`, `thalovant-joke-service`, `thalovant-news-service`
and `thalovant-popculture-service` (`SERVICE_HOSTS`). Never to a bare service
name, an address, a URL with userinfo, or a host an owner typed in.

| Helper | What it does with the token |
|---|---|
| `request_headers(..., url=url)` | Adds it for a service URL. A skill that sends with its own `requests` call passes the URL it posts to. |
| `post_json` | Adds it for a service URL; removes one the kit set (from `request_headers(url=...)`) for any other URL. |
| `network.JsonServiceClient.post` | Adds it for a service URL as an unredirected header, so urllib never copies it onto a redirect. |
| `knowledge.ask_service`, `knowledge_reply`, `knowledge_answer` | Add it to the caller's `headers` (unchanged dict) for a service URL. |
| `service_auth.with_service_token(url, headers)` | Returns a copy of `headers` fit for `url`; a caller's own `Authorization` is left alone. |

- No file, an empty file or one that does not hold a token: no header and no
  error (a file that is not a token logs one warning, never its content).
- The file is read again when it changes (inode, size or modification time),
  so a renewed token is picked up without a restart; a 401 forces one re-read,
  and the request is repeated once only with a different token.
- `requests` already drops `Authorization` when a redirect leaves the host.
- The token is never logged.

[`knowledge_reply(...)`](../thalovant_skillkit/knowledge.py) makes one POST to
`<service_url>/v1/knowledge/answer`, with no retry. Required keyword arguments:
`service_url`, `prompt`, `lang`, `mode`, `max_sources`, `augmentation`,
`age_policy_setting`, `headers`, `timeout`; `logger=None` is optional.
It returns `KnowledgeReply(answer, policy, augmented=False)`; `provenance` is
`"source"`, `"llm-augmented"`, or `None` when there is no answer.

| Policy constant | Meaning |
|---|---|
| `POLICY_NONE` (`""`) | Ordinary outcome, including blank input or general HTTP/network/JSON failure; does not imply that an answer exists. |
| `POLICY_NO_ANSWER` | HTTP 404: the service found no answer. |
| `POLICY_BLOCKED` | Service age policy filtered the answer; preserve that policy decision rather than substituting packaged content. |
| `POLICY_UNAVAILABLE` | Invalid age-policy configuration or an unavailable age classifier; suppress packaged fallback and report unavailability. |

`parse_age_policy` accepts disabled/absent policy as `None`; enabled policy
requires a boolean `enabled` and an age boundary of 13, 16, 18 or 21 (integer
or its exact string), defaulting to 13. Invalid configuration raises `ValueError`;
`knowledge_reply` converts it to `POLICY_UNAVAILABLE`.
`normalize_ai_augmentation` maps supported values to `on`, `off` or default
`auto`; `knowledge_reply` expects the caller to pass the intended mode.
`knowledge_answer(...)` is the compatibility wrapper returning `(answer, policy)`.
A body that is not a JSON object, streamed or not, is a `ValueError` that
`knowledge_reply` reports as `POLICY_NONE` with no answer; the client is not a
general schema validator beyond that, and caller-input/type errors can still
propagate.

### Saying where a slow answer comes from

A lookup takes a few seconds, most of them after the service has chosen its
source. With `Accept: application/x-ndjson` the service announces the source
first (`{"event": "source", "provider": "wikipedia", "pending": true}`), then
the answer or an error. `ask_service(*, service_url, request_payload, headers,
timeout, lang=None)` posts one question and returns the answer document,
raising what `requests` raises; inside a `lookup_notice` it asks for the
stream and tells the visitor what is happening:

| What the service says | What the visitor hears |
|---|---|
| A source, and a slow step follows (`pending: true`) | "From Wikipedia…" at once |
| A source, and nothing follows (`pending: false`) | Nothing: the answer is on its way |
| A source, without saying (an older service) | "From Wikipedia…" if the answer is not there `NOTICE_DELAY` (0.5 s) later |
| Nothing at all for `WORKING_DELAY` (1.2 s) | "Looking it up…", which names nothing |
| An event the kit does not know | Skipped; a malformed source, answer or error, or a stream that ends without an answer, is a `ValueError` |

```python
from thalovant_skillkit.knowledge import knowledge_reply, lookup_notice

with lookup_notice(lambda line: self.speak_to(message, line)) as notice:
    reply = knowledge_reply(...)
notice.names("wikipedia")   # whether the source was already named this turn
```

`lookup_notice(speak)` opens one turn's notice in a context variable, so every
call under it (`knowledge_reply`, or a skill's own `ask_service`) shares it and
the source is named once per turn; `current_notice()` reads it, `None` outside
a turn. A `speak` that raises is logged and never costs the answer. The lines
are `notice_text(lang, provider)` and `working_text(lang)`, from the kit's
`shared_dialog/` in each of the public hubs' eleven languages; `provider_name`
maps the service's ids (`PROVIDER_NAMES`: `web-search` is DuckDuckGo) to the
names a visitor knows. `run_noticing` from 0.26.0 is kept as a no-op wrapper.

## Regional resources CLI

`thalovant-skillkit locales [directory]` checks `locale/regional.json` against
the generated folders. Add `--write` to regenerate and add their tags to
`supported.json`. Exit codes: 0 when current, 1 on errors. A skill without a
manifest needs no migration. `check` also includes this freshness check.


### Authoring a region

Use SkillKit **0.15.0 or later** when a regional translation must also work with
native OVOS intents or code that reads files directly. Keep the common words in
the original language folder and write only the differences in
`locale/regional.json` inside your skill package:

```json
{
  "version": 1,
  "locales": {
    "fr-CA": {
      "source": "fr-FR",
      "overrides": {
        "dialog/garden.watering.dialog": "Cette démo peut parler de la fin de semaine.\n"
      }
    },
    "en-CA": {"source": "en-US", "overrides": {}}
  }
}
```

Each override key is a file path relative to its locale folder. Its value is the
**complete file text**, including `\n` between lines. Keep placeholders such as
`{score}`, JSON keys, vocabulary identifiers before `|`, and regex group names
unchanged. This command copies shared text; it does not translate it for you.

From the skill's repository, run:

```bash
thalovant-skillkit locales --write
thalovant-skillkit check --no-fleet
python -m pytest -q
```

**Expected result:** `fr-CA` contains the Canadian reply plus all the other French
resources. `en-CA` contains the shared English resources. Both tags appear in
`supported.json`, and the checker reports that the skill keeps its contracts.
The earlier fallback test now selects `fr-CA` and expects the new Canadian reply;
update those two assertions after generating this example.

Commit the manifest, generated folders, and updated `supported.json`. Future
edits go in the source language or the manifest, then run `locales --write` again.
Do not edit generated files directly: ordinary `check` reports stale or manually
changed files. `thalovant-skillkit locales` performs the same freshness check
without writing. If a source file is removed, the tool names obsolete generated
files for you to remove explicitly; it never silently deletes them.

Sources must be existing base locales in the same language. Chaining one generated
region to another is not supported. A regional override must name an existing
source file and preserve its placeholders. To add a new resource, put it in the
base locale first. Full validation still belongs to `check` and your tests.
Generation happens during development, with no network calls or extra work when
someone speaks. Generated files are ordinary package data and need the same
wheel checks as other translations.

Start with common regional variants of languages your skill already supports:

| Shared translation | Common regional targets |
| --- | --- |
| `en-US` | `en-CA`, `en-GB`, `en-AU`, `en-NZ` |
| `fr-FR` | `fr-CA`, `fr-BE`, `fr-CH` |
| `es-ES` | `es-MX`, `es-AR`, `es-CO`, `es-US` |
| `de-DE` | `de-AT`, `de-CH` |
| `pt-PT` | `pt-AO`, `pt-MZ` |
| `nl-NL`, `sv-SE` | `nl-BE`, `sv-FI`, respectively |
| `zh-CN` | `zh-SG`; `zh-TW` needs Traditional Chinese wording |

Keep existing regional translations where they already fit. Identical wording
can be inherited honestly; separate folders do not mean separate native-speaker
reviews. Regional English spelling, Canadian French expressions, Swiss German
orthography and Argentine Spanish grammar need contextual review. For Chinese,
[OpenCC's Taiwan configuration](https://github.com/BYVoid/OpenCC#configurations-配置文件)
can help prepare Traditional characters and common Taiwan terms. Check spoken
phrases and regex literals too; conversion does not create a Cantonese translation.
Ask fluent speakers to review important flows before claiming linguistic quality.

## Who is speaking, and what is safe to say or dial

A skill that serves one household's private thing (a media server, the lights, a camera) answers only the
hub's devices that household listed, and says only text that is safe to read aloud. Two modules do that
for every such skill, reconciled from the copies the media and Music Assistant skills had written.

### `thalovant_skillkit.device`: the router's stamp, and nothing else

The hub's home router writes `context["thalovant_home"]` (and, from router 0.5.0, `context["thalovant_connector"]`) on every
utterance from a connection it vouches for, with `device` (the database id of the row) and `device_name`
(its platform-assigned name, `client-<uuid>`). It writes both from the row and overwrites whatever a client
sent, and writes neither for a connection it will not vouch for (a preview or chat bridge, no account).
**Everything else that looks like an identity is the client's own word**: `context["peer"]` is
`<useragent>::<id>::<name>::<session>` with a client-supplied user agent and session (`x::1580::y` makes the tail
read as another client's id), and `source`, `site_id`, `client_id` and the session's copies are no better.
This module has no function that reads any of them.

| Name | Returns |
|---|---|
| `device_identity(context)` | `DeviceIdentity(device_id, name)` from the stamps, or `None`. `thalovant_home` decides (every router since 0.4.1 overwrites it on every client utterance); a `thalovant_connector` stamp, when the key is there at all, must name the same device (before router 0.5.0 a client could write it itself, and the first stamp found used to win). Never raises. `.keys` is the id, the row name, and the row name without `client-`. |
| `device_allowed(context, allowed)` | `True` only when one of those keys equals an entry of `allowed` (folded, whole values). An empty list, a bare string or bytes (not a list), no stamp, a malformed stamp or an allow-list that raises while it is read is `False`. Entries may be strings or integers. |
| `STAMP_KEYS` | `("thalovant_home", "thalovant_connector")`: the only keys believed. The retired `thalovant_music` is not: a client could write it. |

```python
from thalovant_skillkit.device import device_allowed

def handle(self, message):
    if not device_allowed(message.context, self.allowed_devices):   # deny by default
        return self.pass_on(message)
```

### `thalovant_skillkit.safety`: titles to say, servers to dial

| Name | Returns |
|---|---|
| `speakable(value, limit=120)` | A title or name as words only: tags and addresses (`scheme://`, `www.`) removed, angle brackets, control, format (bidi), surrogate, private-use and unassigned characters turned into spaces, one line, at most `limit` characters; `""` for anything that is not text. The work on a hostile value is bounded (it is cut to four times `limit` first). |
| `contains_url(value)` | Whether text carries something address-like. |
| `normalize_base_url(raw)` | `scheme://host:port/prefix` for what an owner typed (a bare `host:port` is http; credentials, query and fragment are dropped), or `""`. |
| `url_problem(url)` | Why a URL must not be dialled, or `""`. The host is read as the resolver reads it (`canonical_host`: Unicode full stops and IDNA labels folded to ASCII, a numbers-and-dots host such as `134744072` as the address it means; a host that cannot be encoded is refused). Refused: an address that is never a server's (link-local, where cloud metadata lives; unspecified; multicast; an IPv4-mapped IPv6 judged as its IPv4), the names a cluster or host gives only to itself (`*.svc`, `*.cluster.local`, `*.internal`, `metadata.google.internal`), and a plain `http://` or `ws://` to a public address or name (the token would cross the internet in clear). |
| `address_problem(address)` | The first rule alone, for an `ipaddress` object. |
| `canonical_host(host)` | The host as the resolver will read it, or `None` when it cannot be encoded. |
| `vetted_addresses(host, port, plain=False)` | The addresses a name resolves to *now*, each checked with `address_problem`; with `plain=True` (an `http://` or `ws://` connection) an answer that is not a private or loopback address is refused too, which is where a LAN name that resolves publicly is stopped. Raises `UnsafeAddress` for a refused or empty answer and `socket.gaierror` when the name does not resolve. A client connects to the returned address, so a name that answers differently the second time cannot move it. |

A name is never resolved by `url_problem`; a client that dials one calls `vetted_addresses(host, port, plain=<the scheme is http or ws>)` at the moment of the call and connects to the address it returns. The kit does not dial or follow redirects for you: refuse redirects in the client that does.

### Older kits: the guard for `device` and `safety`

A kit before 0.37 has neither module, and a hub keeps the kit it loaded at boot, so a skill with a lower floor imports
them behind a guard. The fallback for `device` is to deny everyone; the fallback for `safety` strips tags and
addresses itself:

```python
try:
    from thalovant_skillkit.device import device_allowed
except ImportError:  # a kit before 0.37, still loaded on a hub that upgraded in place
    def device_allowed(context, allowed):
        return False  # fail closed: the skill answers nobody until the pod restarts on the new kit
```

The media skills' shared library does this; a skill that serves a household's private thing should too.

## Shared runtime plumbing

Use these helpers when your skill needs them; they start no network work merely
by being imported. A skill still owns its topic, record schema, session ownership,
spoken fallback and freshness policy. OVOS owns dispatch, audio and scheduling.

| Need | Helper | Lifetime and limits |
|---|---|---|
| Several calls must fit one reply | `network.RequestBudget` | Context-local deadline; nested limits cannot extend it. Always pass its timeout to the transport. |
| A small JSON service request | `network.JsonServiceClient` | One POST attempt, identified headers, object-only response, 2 MiB default body cap, 30-second default per-URL failure cooldown, at most 128 cooldown entries. |
| Refresh data away from the reply path | `workers.PeriodicWorker` | One cooperative daemon thread per instance; immediate pass, then an interruptible interval. No overlapping passes. |
| Optional household state storage | `storage.JsonStateStore` | Existing Redis/Sentinel cache and PostgreSQL table; drivers load only when configured. No cross-backend transaction. |
| Find packaged sounds once | `assets.bundled_files` | Immutable tuple of paths, at most 128 directory/pattern entries; never caches audio bytes. |
| Vary multiple sound or dialog pools | `selection.ShuffleBagPool` | At most 128 bags by default, instance-local history protected by a lock; changed choices replace a keyed bag. |
| Speak a varied translated reply | `self.speak_varied_dialog` | OVOS renders and speaks, including its overrides; Kit chooses a line. Ordinary `speak_dialog` is unchanged. |
| OCP playback with follow-up turns | `skill.ThalovantConversationalCommonPlaySkill` | Native Workshop 8/9 behavior with Kit helpers; unavailable (`None`) if upstream OCP is absent. |

### Network work

```python
from thalovant_skillkit.network import JsonServiceClient, RequestBudget

budget = RequestBudget()
client = JsonServiceClient("my-skill", "1.0.0", budget=budget)

def fetch_answer(service_url, question):
    with budget.limit(2.0):
        result = client.post(service_url, {"question": question}, timeout=1.0)
    return result  # A dict, or None: the caller decides what to say.
```

Create the client once per skill instance so cooldown history survives turns.
`post()` returns `None` for an empty URL, an exhausted budget, an active cooldown,
network failure, invalid JSON, a non-object result or an oversized response.
It does not retry a POST: the server might already have performed its action.
The one exception is a 401 from a service after which the token file holds a
different token: the request was refused before it was handled.
Successful replies are **not cached**, and no response is shared between speakers.
An exhausted preflight budget does not start a failure cooldown. A failure on one
URL does not suppress another URL. Use stable, configured service URLs rather
than putting the utterance into the URL.

`budget.read(response)` returns a complete body or raises `TimeoutError` or
`ValueError`; it never silently truncates. Deadline checks occur between reads.
They cannot interrupt a blocked socket, DNS lookup or transport: the budget is
not hard wall-clock cancellation. Supply finite transport timeouts too. A stalled
read can overshoot the deadline by one socket timeout. `limit()` restores the
previous context on exit, including exceptions, and separates concurrent threads.

### Background refresh

```python
from thalovant_skillkit.workers import PeriodicWorker

# In initialize(): self.refresh = PeriodicWorker(self.refresh_catalog,
#     interval=600, name="catalog-refresh"); self.refresh.start()
# refresh_catalog(self, stop_event) must bound each request and check cancellation.
# In shutdown(): self.refresh.stop(timeout=1.0); super().shutdown()
```

`start()` returns false if its previous thread is still alive. `stop()` signals
cancellation, joins for at most the supplied timeout and returns whether it has
exited. Python cannot forcibly kill the callback. A failed pass is logged and
retried after the normal interval. Keep credentials and private payloads out of
callback exception messages. Use OVOS scheduling for alarms or user deadlines;
this worker is for optional refresh work.

### Optional shared persistence

```python
from thalovant_skillkit.storage import JsonStateStore

store = JsonStateStore("household", {}, env_prefix="MY_SKILL", default_key="records")
records = store.load()  # None when unavailable; use the skill's local fallback.
```

Install `redis` for Redis/Sentinel and `psycopg` for PostgreSQL when used. Settings
win over the prefixed environment, then generic `REDIS_URL`,
`REDIS_SENTINEL_URLS`, `REDIS_SENTINEL_SERVICE_NAME` and `DATABASE_URL`.
`state_key` / `<prefix>_STATE_KEY` selects the key; `default_key` is the fallback.
Redis uses `thalovant:<scope>:<key>`; PostgreSQL keeps the existing
`thalovant_skill_state(scope, key, value, updated_at)` table. No data migration is
needed for Alarm, Timer, Reminder or Stopwatch.

(For several owners' records prefer `RecordStore`, below: this document is rewritten whole on every save.)

A cache miss reads PostgreSQL and fills Redis; `load(redis=False)` reads PostgreSQL
only and writes nothing back (for a caller Redis has refused the key, which sets
`redis_refused`). `save(list_of_records)` attempts both stores independently,
without a success guarantee. A PostgreSQL that cannot be reached is left alone for
`POSTGRES_RETRY_SECONDS` (60 s) and then tried again, and a connection that fails a
query is closed and replaced on the next call. A missing driver, or a Redis client
that cannot be built, turns that backend off for this store instance.
Skills must validate records, enforce speaker ownership and retain their existing
local recovery path. This helper adds no in-memory copy or TTL that could hide a
new state write. It is not a transactional database or a replacement for a
service-owned persistence contract.

### Per-owner records

`JsonStateStore` keeps all owners' records as one document, and every save
rewrites all of it: two owners or two hub pods saving together overwrite each
other. A skill that keeps a person's records (alarms, reminders, timers, lists)
should use `RecordStore` instead:

```python
from thalovant_skillkit.records import RecordStore, RecordStoreError

store = RecordStore("alarm", self.settings, env_prefix="THALOVANT_ALARM",
                    default_key="alarms")                    # same settings as JsonStateStore
records = store.load_all_with_legacy()                       # at start; None = keep the settings
store.save_changes(before, after)                            # writes only what changed
mine = store.load_owner(owner)                               # one person's records, afresh
```

The records are dicts with an `id` and an `owner` (`id_field` and `owner_field`
rename them). Redis keeps a hash per owner, PostgreSQL a row per record, every
write is one step per record, and the owner is hashed into every key. The old
whole document is imported once and never touched. `testing.FakeRecordStore`
needs no servers. The full contract, the swap for an existing skill, how to
inspect a person's records and the limits are in [records.md](records.md).

Under a Redis user limited to some keys, set `key_prefix` (or `THALOVANT_RECORDS_KEY_PREFIX`)
so every key is `<prefix>:records:v1:...`; a refusal is logged once with the ACL it needs. See
[records.md](records.md#operators-running-under-a-per-hub-redis-user).

### Cache and selection choices

`bundled_files(directory, "*.ogg")` is for immutable package assets. Call
`bundled_files.cache_clear()` after an in-place asset update; inspect
`cache_info()` while profiling. Do not use it for user upload directories.
`SkillResources.clear_cache()` similarly refreshes translations between turns.
These operations do not atomically coordinate concurrent file edits.

`ShuffleBagPool.draw(items, count=1, key=..., avoid=...)` returns a list.
Without an explicit key, choices must be hashable and equal pools share history.
A key such as `(lang, dialog_name)` permits changed choices to replace an old bag.
`avoid` suppresses a speaker's last choice on the first draw when alternatives
exist. `remember(item)` records an exact replay delivered outside `draw()`.
Capacity eviction discards history, not sound files or user state.

Call `self.speak_varied_dialog("quiz.correct", {"name": "Sam"})` from an intent
handler. Place curated lines in the usual translated `.dialog` files, keep
placeholder names consistent, and use `expect_response=True` when inviting an
answer. This preserves native OVOS speech and resource overrides.

See [runtime measurements and reproduction](performance.md) for the measured
0.18.0 fleet migration, including fresh-process setup and warm request costs.
