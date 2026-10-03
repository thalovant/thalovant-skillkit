# SkillKit 0.18.0 reference

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
`fold_tight`, `fold_words` and `strip_accents`. Use
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
meta=None, wait=False)` speaks `text` to whoever sent `message`: it forwards that message,
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
many seconds. A `Speech` sends its SSML as `utterance_ssml`.

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

Why `.ssml` and not `.ssml.dialog`: OVOS reads every `.dialog` file as a plain
template in which `<name>` names a vocabulary. It would load
`joke.ssml.dialog` as a dialog called `joke.ssml` and raise on the first
`<break/>`, and `ovos-spec-lint` reports it. OVOS ignores a `.ssml` file.

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
| `<prosody>` | `rate` (named or a percentage), `volume` (named or dB) |
| `<emphasis>` | `level`: `strong`, `moderate`, `reduced` or `none` |
| `<lang>`, `<voice>` | `xml:lang` |
| `<say-as>` | `interpret-as`: `characters`, `spell-out`, `digits` or `telephone` |
| `<sub>` | `alias` |
| `<phoneme>` | `ph`, and `alphabet="ipa"` |

Thalovant voices read `pitch`, `<audio>`, `<mark>` and `amazon:*` as plain
words, so the check reports them.

### What the check reports

`check_ssml(skill_root)` is part of `check_all` and runs under both
`thalovant-skillkit check` and `check --fleet-only`. Every error fails the check:

- a plain `.dialog` line that holds an SSML tag;
- a `.ssml` file with no `.dialog` beside it, or a different number of lines;
- a twin line that is not well-formed XML, or uses an unsupported tag,
  attribute or value;
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
and returns `True`; an empty reply returns `False`. If you override
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

Install with `python -m pip install --pre "thalovant-skillkit[testing]==0.12.0"`;
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

[`request_headers(skill_name, skill_version, user_agent)`](../thalovant_skillkit/service.py)
sets User-Agent, a fresh X-Request-ID, skill name and version headers.
It does not supply authentication.

`post_json(url, payload, *, headers=None, timeout=2.4, attempts=2, client=requests)`
returns `response.json()` or `None` after failure. It makes at least one attempt,
returns immediately for HTTP 4xx (including 429), and retries connection errors,
HTTP 5xx and unusable JSON up to the attempt limit without backoff. Timeout is
passed to each request; it is not a total wall-clock deadline. The decoded JSON
is **not validated as a dictionary**, despite the return annotation. Validate
the response your skill requires; `None` can also be a decoded JSON null.

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
The knowledge client expects a JSON object response; it is not a general schema
validator, and caller-input/type errors can still propagate.

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

A cache miss reads PostgreSQL and fills Redis. `save(list_of_records)` attempts
both stores independently, without a success guarantee. Connection setup failures
disable that backend for this store instance; rebuild the store to retry setup.
Skills must validate records, enforce speaker ownership and retain their existing
local recovery path. This helper adds no in-memory copy or TTL that could hide a
new state write. It is not a transactional database or a replacement for a
service-owned persistence contract.

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
