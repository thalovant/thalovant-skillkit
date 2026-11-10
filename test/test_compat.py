"""A skill can ask for a kit name an older loaded kit lacks and still load."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

from thalovant_skillkit import compat, ssml
from thalovant_skillkit.compat import (
    PLAIN_HELPERS,
    kit_at_least,
    kit_attr,
    kit_version,
    speech_style_or_none,
    ssml_helper,
)

COMPAT_FILE = Path(compat.__file__)


@pytest.fixture
def old_kit(monkeypatch):
    """The kit as a hub that upgraded in place still holds it: `ssml` before `SpeechStyle`."""
    old = types.ModuleType("thalovant_skillkit.ssml")
    old.Speech = ssml.Speech
    old.spell = ssml.spell
    monkeypatch.setitem(sys.modules, "thalovant_skillkit.ssml", old)
    monkeypatch.setattr(sys.modules["thalovant_skillkit"], "__version__", "0.29.1")
    return old


def test_the_loaded_version_is_what_is_asked():
    from thalovant_skillkit.version import __version__

    assert kit_version() == tuple(int(part) for part in __version__.split("."))
    assert kit_at_least("0.34") and kit_at_least("0.35.0") and kit_at_least("0")
    assert not kit_at_least("99.0")


def test_a_kit_before_speech_style_gives_none_not_an_import_error(old_kit):
    assert kit_version() == (0, 29, 1)
    assert not kit_at_least("0.34") and kit_at_least("0.29")
    assert speech_style_or_none(rate="95%", sentence_break="350ms") is None
    assert kit_attr("ssml", "SpeechStyle") is None
    assert kit_attr("ssml", "SpeechStyle", "x") == "x"
    assert kit_attr("not_a_module", "x", 5) == 5


def test_the_current_kit_gives_the_real_style():
    style = speech_style_or_none(rate="95%", sentence_break="350ms")
    assert style == ssml.SpeechStyle(rate="95%", sentence_break="350ms")


def test_a_field_the_loaded_kit_does_not_know_is_left_out(monkeypatch):
    import dataclasses

    @dataclasses.dataclass(frozen=True)
    class Older:
        rate: str | None = None

    fake = types.ModuleType("thalovant_skillkit.ssml")
    fake.SpeechStyle = Older
    monkeypatch.setitem(sys.modules, "thalovant_skillkit.ssml", fake)
    assert speech_style_or_none(rate="95%", pitch="+1st", say_as=False) == Older(rate="95%")


def test_a_value_no_voice_reads_is_still_the_skills_mistake():
    with pytest.raises(ValueError):
        speech_style_or_none(rate="very-fast-indeed")


def test_a_helper_the_kit_lacks_is_its_plain_words(old_kit):
    assert ssml_helper("spell") is old_kit.spell
    assert ssml_helper("cardinal")("1,200") == "1,200"
    assert ssml_helper("as_time")("14 h 30", "hms24") == "14 h 30"
    assert ssml_helper("sub")("km/h", "kilometres per hour") == "kilometres per hour"
    assert ssml_helper("phoneme")("tomato", "təˈmeɪtoʊ", alphabet="ipa") == "tomato"
    assert ssml_helper("pause")("1s") == "" and ssml_helper("mark")("m") == ""
    assert ssml_helper("breath")("short") == ""
    assert ssml_helper("say")("A", None, ssml_helper("pause")("1s"), "B") == "A B"
    assert ssml_helper("markup")('<s>Hi <b>{name}</b></s> &amp; bye', name="Ada") == "Hi Ada & bye"
    assert type(ssml_helper("cardinal")("1")) is str


def test_a_typo_is_not_mistaken_for_an_old_kit():
    with pytest.raises(ValueError, match="not a thalovant_skillkit.ssml helper"):
        ssml_helper("cardinall")


def test_every_helper_the_kit_exports_has_a_plain_stand_in():
    helpers = {name for name in ssml.__all__
               if callable(getattr(ssml, name)) and name[0].islower()
               and name not in {"carries_markup", "escape", "looks_like_ssml", "render_line",
                                "speech_parts", "strip_tags", "to_plain", "validate",
                                "auto_twin"}}
    assert helpers == set(PLAIN_HELPERS), helpers ^ set(PLAIN_HELPERS)


@pytest.mark.parametrize("name", sorted(PLAIN_HELPERS))
def test_the_stand_in_says_what_the_real_helper_says_as_plain_words(name):
    """With the kit present `ssml_helper(name)` is the real helper, and its plain words are the
    stand-in's: the same sentence is spoken with or without the kit's help."""
    samples = {
        "say": (("A", "B"), {}), "pause": (("1s",), {}), "mark": (("m",), {}),
        "breath": ((), {}), "sub": (("km/h", "kilometres"), {}),
        "markup": (("<s>{x}</s>",), {"x": "hi"}), "foreign": (("café", "fr-FR"), {}),
        "emphasis": (("now",), {}), "phoneme": (("tomato", "təˈmeɪtoʊ"), {}),
        "prosody": (("slow",), {"rate": "slow"}), "pitch": (("up", "+2st"), {}),
        "vocal_tract": (("low", "+10%"), {}), "as_date": (("2026-11-09",), {}),
        "as_time": (("14:30",), {}), "auto_breaths": (("One. Two.",), {}),
    }
    args, kwargs = samples.get(name, (("5 km",), {}))
    real = ssml_helper(name)
    assert real is getattr(ssml, name)
    assert str(real(*args, **kwargs)) == PLAIN_HELPERS[name](*args, **kwargs)


def test_a_skill_with_the_documented_guard_loads_on_an_older_kit_and_one_without_it_does_not(
        tmp_path):
    """The hub case end to end: old kit in memory, the new `compat.py` on disk."""
    kit = tmp_path / "thalovant_skillkit"
    kit.mkdir()
    (kit / "__init__.py").write_text('__version__ = "0.29.1"\n')
    (kit / "ssml.py").write_text("class Speech(str):\n    pass\n\ndef spell(t):\n    return t\n")
    (kit / "compat.py").write_text(COMPAT_FILE.read_text())
    skill = tmp_path / "skill.py"
    skill.write_text(textwrap.dedent('''
        import sys
        mode = sys.argv[1]
        if mode == "unguarded":
            from thalovant_skillkit.ssml import SpeechStyle
        elif mode == "try":
            try:
                from thalovant_skillkit.ssml import SpeechStyle
            except ImportError:
                SpeechStyle = None
            assert SpeechStyle is None
        else:
            from thalovant_skillkit.compat import speech_style_or_none, ssml_helper
            assert speech_style_or_none(rate="95%") is None
            assert ssml_helper("cardinal")("1,200") == "1,200"
        print("loaded")
    '''))

    def load(mode):
        return subprocess.run([sys.executable, str(skill), mode], cwd=tmp_path,
                              env={"PATH": "/usr/bin"}, capture_output=True,
                              text=True, timeout=60)

    broken = load("unguarded")
    assert broken.returncode != 0 and "cannot import name 'SpeechStyle'" in broken.stderr
    for mode in ("try", "compat"):
        result = load(mode)
        assert result.returncode == 0 and result.stdout.strip() == "loaded", result.stderr
