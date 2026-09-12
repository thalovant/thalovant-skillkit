# SkillKit 0.10.0 reference

Practical contracts for the released Python API and CLI. Start with the
[README](../README.md) for installation, base-class choice and a complete skill.
Source links below contain the full signatures. OVOS owns intent dispatch,
session identity, speech, playback, scheduling and lifecycle hooks.

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

## Locale resources and base helpers

Create `SkillResources(locale_dir, default_lang="en-US")`, or use
`self.locale_resources` on a SkillKit base. The base finds `locale/` beside the
skill class, walking its class hierarchy; `LOCALE_DIR` overrides discovery.
See [locale.py](../thalovant_skillkit/locale.py) and
[skill.py](../thalovant_skillkit/skill.py).

Base flags `REQUIRES_NETWORK`, `REQUIRES_INTERNET` and `REQUIRES_GUI` default to
`False`. Each sets the corresponding `*_before_load` and `requires_*` values in
native `runtime_requirements`, with the inverse `no_*_fallback` value. Override
that property when these coupled defaults do not fit your skill.
`ThalovantCommonPlaySkill` is `None` when the installed workshop cannot provide
its upstream Open Common Play base.

Language selection is exact standardized directory → first alphabetically
sorted directory with the same primary language → configured default locale.
For example, `fr-CA` can select bundled `fr-FR`. This does not guarantee that
the chosen/default directory or a requested file exists.

| Resource operation | Behavior |
|---|---|
| `available_langs()` | Sorted directory names under the locale root. |
| `lang(lang)` | Resolve and cache the language choice. |
| `candidate_langs(lang)` | Resolved locale, then default locale, without duplicates. |
| `lines(lang, folder, filename, fallback=False)` | Cached tuple of stripped, nonblank, non-comment lines. Always resolves language; `fallback=True` also tries the default locale when the file has no usable lines. |
| `vocab(voc_name, lang)` | Lines from `vocab/<name>.voc`, without secondary file fallback. |
| `dialog_lines(name, lang)` | Lines from `dialog/<name>.dialog`, with default-locale fallback. |
| `voc_match(voc_name, utterance, lang=None)` | Containment match against resolved then default vocabulary; returns a boolean. |
| `voc_term(voc_name, utterance, lang=None)` | Longest matching folded term in the first matching candidate locale, or `""`. |
| `voc_match_lang(voc_name, utterance, lang=None)` | Candidate locale whose vocabulary matched, or `""`. |

Caches belong to each `SkillResources` instance. Missing files are cached too;
there is no public invalidation method or file watcher. Recreate the resource
object after changing locale files during development.

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
Missing files return the dialog name; missing arguments or malformed formatting
return the raw chosen template. In contrast, `SkillResources.dialog` chooses
the **first** line, does not expand literal `\n`, and catches only missing
format arguments (`KeyError`/`IndexError`), not malformed braces (`ValueError`).
Use native `self.speak_dialog` for OVOS's speech renderer and delivery behavior.

`self.setting(key, default=None)` returns the default for unreadable settings,
missing keys or a stored `None`. `False`, `0` and `""` are retained.
`preview_reply(utterance="", lang=None, context=None)` calls your text-only
`reply`; it returns `""` for an empty answer or `NotImplementedError`. It does
not replay a skill's audio or simulate its intent handler.

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
callbacks or produce replies for `wait_for_response`. Use it for small unit
tests, and the following optional helpers for framework integration.

Install with `python -m pip install --pre "thalovant-skillkit[testing]==0.10.0"`;
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
`session` is the latest captured carrier matching the source's declared session
ID, deserialized to an OVOS Session; it is `None` when the source declares no ID.
Completion alone does not prove correct routing, replies or session isolation:
assert those outcomes in your test.

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

| CLI option | Effect |
|---|---|
| `check [directory]` | Local contracts plus the default published fleet model when the skill has intents. Directory defaults to the current directory. |
| `--no-fleet` | Disable the published model. Without `--fleet`, only local contracts run. |
| `--fleet-only` | Skip local contracts; incompatible with `--no-fleet`. |
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
