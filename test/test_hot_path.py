"""The utterance path must not cost anything worth measuring.

Everything here runs once per thing a person says, so a regression is felt as a
slower assistant rather than seen as a failing test. Measured on the Jetson the
fleet runs on, a hub round-trip is about 160 milliseconds; the whole of this
library's share of that is a few tens of microseconds.

The ceilings are deliberately loose -- roughly ten times what the code costs --
because a shared CI runner is not a benchmark rig. They catch an order of
magnitude, which is what a real regression looks like: a cache removed, a file
read moved back onto the hot path, a lock introduced.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from thalovant_skillkit import SkillResources, contains_term, message_lang, utterance
from thalovant_skillkit.testing import message

UTTERANCE = "what is the latest news about the weather in montreal today please"


@pytest.fixture
def resources(tmp_path: Path) -> SkillResources:
    (tmp_path / "en-US" / "vocab").mkdir(parents=True)
    (tmp_path / "en-US" / "vocab" / "Big.voc").write_text(
        "\n".join(f"term{i} phrase" for i in range(30)) + "\nnews\n", encoding="utf-8")
    return SkillResources(tmp_path)


def _microseconds(work, runs: int) -> float:
    work()  # warm the caches the real path also warms
    started = time.perf_counter()
    for _ in range(runs):
        work()
    return (time.perf_counter() - started) / runs * 1e6


def test_matching_a_vocabulary_stays_cheap(resources):
    """A vocabulary is folded once per language and file, not per call."""
    cost = _microseconds(lambda: resources.voc_match("Big", UTTERANCE, "en-US"), 2000)

    assert cost < 500, f"voc_match cost {cost:.0f}us against a ~28us budget"


def test_reading_a_message_stays_cheap():
    msg = message(UTTERANCE, lang="en-US")

    cost = _microseconds(lambda: (utterance(msg), message_lang(msg, "en-US")), 2000)

    assert cost < 100, f"reading a message cost {cost:.0f}us against a ~1.4us budget"


def test_resolving_a_language_does_not_touch_the_disk(resources):
    """`lang()` walks the locale tree the first time and remembers after."""
    cost = _microseconds(lambda: resources.lang("en-US"), 5000)

    assert cost < 20, f"lang() cost {cost:.0f}us against a ~0.07us budget"


def test_a_single_term_check_stays_cheap():
    cost = _microseconds(lambda: contains_term(UTTERANCE, "news", "en-US"), 5000)

    assert cost < 50, f"contains_term cost {cost:.0f}us against a ~0.5us budget"


def test_text_and_locale_helpers_take_no_locks_on_the_utterance_path():
    """Pure message/text/resource helpers must not serialise unrelated skills.

    The caches are plain dicts and `functools.lru_cache`; neither blocks. This
    reads the source rather than the behaviour, because a lock that is only
    contended under load will not show up in a single-threaded test. Stateful
    opt-in helpers such as SessionStateStore have a separate per-instance lock;
    they are not imported or used by these stateless helpers.
    """
    import thalovant_skillkit

    package = Path(thalovant_skillkit.__file__).parent
    offenders = {}
    for name in ("message", "text", "vocab", "locale"):
        module = package / f"{name}.py"
        source = module.read_text(encoding="utf-8")
        # Only the executable lines: the word appears in prose explaining why.
        code = "\n".join(
            line for line in source.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        for banned in ("threading.Lock", "threading.RLock", "Semaphore", "time.sleep"):
            if banned in code:
                offenders.setdefault(module.name, []).append(banned)

    assert offenders == {}, f"blocking primitives on the utterance path: {offenders}"
