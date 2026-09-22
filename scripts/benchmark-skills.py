"""Measure local skill paths with network disabled.

Usage: python benchmark-skills.py WORKTREE_ROOT OUTPUT_JSON
WORKTREE_ROOT contains SkillKit, News, Fart, Timer and Weather checkouts.
Run with the same installed dependencies for both revisions, in fresh processes.
"""

import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

root, output = Path(sys.argv[1]), Path(sys.argv[2])
for name in (
    "thalovant-skillkit",
    "thalovant-skill-news",
    "thalovant-skill-fart",
    "thalovant-skill-timer",
    "thalovant-skill-weather",
):
    sys.path.insert(0, str(root / name))
with tempfile.TemporaryDirectory() as temp:
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        os.environ[key] = str(Path(temp) / key)
    os.environ["THALOVANT_NEWS_WARM_AUDIO"] = "0"
    import_start = time.perf_counter_ns()
    import thalovant_skill_fart as fart
    import thalovant_skill_news as news
    import thalovant_skill_timer as timer
    import thalovant_skill_weather as weather
    from ovos_utils.ocp import MediaType

    def offline(*args, **kwargs):
        raise OSError("benchmark forbids network")

    news.urlopen = offline
    import_us = (time.perf_counter_ns() - import_start) / 1000
    construct_start = time.perf_counter_ns()
    skill = news.ThalovantNewsSkill()
    sounds = fart.FartSkill()
    construct_us = (time.perf_counter_ns() - construct_start) / 1000

    def measure(fn, runs=1000):
        fn()
        values = []
        for _ in range(7):
            start = time.perf_counter_ns()
            for _ in range(runs):
                fn()
            values.append((time.perf_counter_ns() - start) / runs / 1000)
        return {
            "median_us": statistics.median(values),
            "min_us": min(values),
            "max_us": max(values),
            "runs": runs,
            "repeats": 7,
        }

    results = {
        "module_import": {"median_us": import_us},
        "news_fart_construction": {"median_us": construct_us},
        "news_preview": measure(lambda: skill.preview_reply("Play NPR news.", lang="en-US"), 500),
        "news_ocp_search": measure(
            lambda: list(skill.search_news("Play NPR news.", MediaType.NEWS)), 500
        ),
        "news_catalog": measure(lambda: skill.read_db(langs=["en-US", "en"])),
        "fart_sound_choice": measure(lambda: sounds._pick_sounds(3)),
        "timer_regional_lines": measure(
            lambda: timer._resource_lines("fr-CA", "regex", "label.rx"), 5000
        ),
        "weather_regional_lines": measure(
            lambda: weather._resource_lines("fr-CA", "vocab", "weather.voc"), 5000
        ),
    }
    skill.shutdown()
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(output)
