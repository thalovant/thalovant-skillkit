"""Intent expansion, the corpus round-trip, and what the fleet check reports.

The embedding model is not loaded here; `find_near` is exercised in
`test_fleet_model.py` only when the model is in the local cache.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from thalovant_skillkit import fleet, intents


def test_alternations_expand_and_empty_choice_means_optional():
    assert set(intents.expand("(what|which) day")) == {"what day", "which day"}
    assert set(intents.expand("cancel (all |)alarms")) == {"cancel all alarms", "cancel alarms"}


def test_nested_groups_expand():
    assert set(intents.expand("(set|(create|make)) a timer")) == {
        "set a timer", "create a timer", "make a timer"}


def test_plain_and_unbalanced_lines_pass_through():
    assert intents.expand("what time is it") == ["what time is it"]
    assert intents.expand("what (time is it") == ["what (time is it"]


def test_expansion_is_capped(monkeypatch):
    monkeypatch.setattr(intents, "EXPANSIONS_PER_LINE", 10)
    assert len(intents.expand(" ".join("(a|b|c|d)" for _ in range(6)))) == 10


def test_clean_neutralises_slots_and_folds_spacing():
    assert intents.clean("Did I ask   about {query}?") == "did i ask about something?"
    assert intents.clean("weather in {city}") == intents.clean("weather in {place}")


def _skill(tmp_path: Path, name: str, files: dict[str, str], langs=("en-US",)) -> Path:
    """A minimal skill checkout: package, entry point, locale tree."""
    root = tmp_path / f"thalovant-skill-{name}"
    package = root / f"thalovant_skill_{name.replace('-', '_')}"
    (package / "locale").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "locale" / "supported.json").write_text(json.dumps({"locales": list(langs)}))
    for relative, text in files.items():
        path = package / "locale" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (root / "pyproject.toml").write_text(f'''
[project]
name = "thalovant-skill-{name}"
version = "0.0.1"
[project.entry-points."opm.skill"]
"thalovant-skill-{name}.thalovant" = "thalovant_skill_{name.replace('-', '_')}:Skill"
''')
    return root


@pytest.fixture
def fleet_dir(tmp_path: Path) -> Path:
    weather = _skill(tmp_path, "weather", {
        "en-US/intents/rain.intent": "will it (rain|pour)\n# comment\n\ndo i need an umbrella\n",
        "fr-FR/rain.intent": "va-t-il pleuvoir\n",
    }, langs=("en-US", "fr-FR"))
    _skill(tmp_path, "time", {"en-US/time.intent": "what time is it\n"})
    assert weather.exists()
    return tmp_path


def test_intent_lines_read_both_layouts_with_line_numbers(fleet_dir: Path):
    skill_id, locale_dir = fleet.skill_identity(fleet_dir / "thalovant-skill-weather")
    assert skill_id == "thalovant-skill-weather.thalovant"
    root = fleet_dir / "thalovant-skill-weather"
    lines = intents.intent_lines(root, locale_dir, "en-US", skill_id)
    assert [(line.intent, line.line, line.text) for line in lines] == [
        ("rain", 1, "will it rain"), ("rain", 1, "will it pour"),
        ("rain", 4, "do i need an umbrella")]
    assert lines[0].file.endswith("locale/en-US/intents/rain.intent")
    fr = intents.intent_lines(root, locale_dir, "fr-FR", skill_id)
    assert [line.text for line in fr] == ["va-t-il pleuvoir"]


def test_corpus_round_trip(fleet_dir: Path, tmp_path: Path):
    skills = []
    for name in ("weather", "time"):
        root = fleet_dir / f"thalovant-skill-{name}"
        skill_id, locale_dir = fleet.skill_identity(root)
        skills.append((skill_id, root, locale_dir, {"repo": name, "sha": "abc"}))
    corpus = intents.build_corpus(skills, "en-US")
    path = intents.write_corpus(tmp_path / "corpus", corpus)
    loaded = intents.load_corpus(path)
    assert loaded["version"] == intents.CORPUS_VERSION
    assert loaded["skills"]["thalovant-skill-time.thalovant"] == {"repo": "time", "sha": "abc"}
    texts = {(line.skill, line.text) for line in intents.corpus_lines(loaded)}
    assert ("thalovant-skill-time.thalovant", "what time is it") in texts
    assert ("thalovant-skill-weather.thalovant", "will it pour") in texts
    assert all(line.lang == "en-US" for line in intents.corpus_lines(loaded))


def test_load_refuses_another_version(tmp_path: Path):
    path = tmp_path / "en-US.json"
    path.write_text(json.dumps({"version": 99, "lang": "en-US", "lines": [], "skills": {}}))
    with pytest.raises(ValueError, match="version"):
        intents.load_corpus(path)


def test_fleet_check_reports_duplicates_and_self_duplicates(fleet_dir: Path, tmp_path: Path):
    # A new skill copying a weather sentence, and repeating one of its own.
    new = _skill(tmp_path / "new", "pulse", {
        "en-US/pulse.intent": "what is on tonight\nwill it rain\n",
        "en-US/again.intent": "what is on tonight\n",
    })
    skills = []
    for name in ("weather", "time"):
        root = fleet_dir / f"thalovant-skill-{name}"
        skill_id, locale_dir = fleet.skill_identity(root)
        skills.append((skill_id, root, locale_dir, {}))
    intents.write_corpus(tmp_path / "corpus", intents.build_corpus(skills, "en-US"))

    findings, notes = fleet.check_fleet(new, tmp_path / "corpus", near=False)
    kinds = sorted((f.kind, f.mine.text, f.theirs.skill) for f in findings)
    assert kinds == [
        ("duplicate", "will it rain", "thalovant-skill-weather.thalovant"),
        ("self", "what is on tonight", "thalovant-skill-pulse.thalovant"),
    ]
    duplicate = next(f for f in findings if f.kind == "duplicate")
    assert duplicate.fails and duplicate.mine.line == 2
    assert "weather" in duplicate.describe() and "rain.intent:1" in duplicate.describe()
    assert not next(f for f in findings if f.kind == "self").fails
    assert notes == []


def test_fleet_check_skips_its_own_corpus_entries(fleet_dir: Path, tmp_path: Path):
    """Re-checking a skill that is already in the corpus must not report
    every one of its sentences as a duplicate of itself."""
    root = fleet_dir / "thalovant-skill-weather"
    skill_id, locale_dir = fleet.skill_identity(root)
    intents.write_corpus(tmp_path / "corpus",
                         intents.build_corpus([(skill_id, root, locale_dir, {})], "en-US"))
    findings, notes = fleet.check_fleet(root, tmp_path / "corpus", near=False)
    assert findings == []
    assert notes == ["fr-FR: no fleet corpus, only this skill's own files compared"]


def test_render_is_an_annotation_under_actions(fleet_dir: Path, monkeypatch):
    line = intents.IntentLine("s", "i", "en-US", "locale/en-US/i.intent", 7, "x", "x")
    other = intents.IntentLine("t", "j", "en-US", "locale/en-US/j.intent", 1, "x", "x")
    finding = fleet.Collision("duplicate", line, other, 1.0)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert fleet.render(finding).startswith("locale/en-US/i.intent:7: ")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert fleet.render(finding).startswith("::error file=locale/en-US/i.intent,line=7::")
    warning = fleet.Collision("near", line, other, 0.9)
    assert fleet.render(warning).startswith("::warning file=")


def test_predicted_reports_only_confident_other_skill_labels(monkeypatch, tmp_path: Path):
    """The classifier finding: another skill's label above the threshold is
    reported, my own label and low-confidence guesses are not."""
    np = pytest.importorskip("numpy")
    inference = pytest.importorskip("model2vec.inference")

    class FakePipeline:
        classes_ = np.array(["weather:rain", "mine:garden", "joke:fact"])

        @classmethod
        def from_pretrained(cls, path):
            return cls()

        def predict_proba(self, texts):
            table = {
                "will it rain today": [0.95, 0.03, 0.02],   # weather, confident
                "water the garden": [0.10, 0.85, 0.05],     # mine
                "what time is it there": [0.40, 0.30, 0.30],  # nobody, unsure
                "tell me a plant fact": [0.02, 0.03, 0.95],  # joke, confident
            }
            return np.array([table[t] for t in texts])

    monkeypatch.setattr(inference, "StaticModelPipeline", FakePipeline)
    mine = [intents.IntentLine("mine", "garden", "en-US", "f.intent", i, t, t)
            for i, t in enumerate(["will it rain today", "water the garden",
                                   "what time is it there", "tell me a plant fact"], 1)]
    found = fleet.find_predicted(mine, tmp_path, "mine")
    assert [(f.mine.text, f.theirs.skill, f.theirs.intent, round(f.score, 2)) for f in found] == [
        ("will it rain today", "weather", "rain", 0.95),
        ("tell me a plant fact", "joke", "fact", 0.95),
    ]
    assert all(f.kind == "predicted" and not f.fails for f in found)
    assert "joke's fact" in found[1].describe()


def test_locale_langs_drops_bad_tags_and_missing_trees(tmp_path: Path):
    assert intents.locale_langs(tmp_path / "nowhere") == []
    locale = tmp_path / "locale"
    locale.mkdir()
    (locale / "supported.json").write_text(json.dumps(
        {"locales": ["en-US", "zh-Hant-TW", "../../etc", "", 7, "fr-FR/../x"]}))
    assert intents.locale_langs(locale) == ["en-US", "zh-Hant-TW"]
    (locale / "supported.json").unlink()
    for name in ("en-US", "pt", "not a tag", "dialog"):
        (locale / name).mkdir()
    assert intents.locale_langs(locale) == ["en-US", "pt"]


def test_write_corpus_refuses_a_tag_that_is_a_path(tmp_path: Path):
    with pytest.raises(ValueError, match="language tag"):
        intents.write_corpus(tmp_path, {"lang": "../escape", "lines": [], "skills": {},
                                        "version": intents.CORPUS_VERSION, "built": ""})


def test_check_fleet_on_a_skill_without_locale_reports_nothing(tmp_path: Path):
    root = _skill(tmp_path, "bare", {})
    import shutil
    shutil.rmtree(root / "thalovant_skill_bare" / "locale")
    assert fleet.check_fleet(root, tmp_path / "corpus", near=False) == ([], [])


def test_indexed_duplicates_name_the_other_owner_only(tmp_path: Path):
    """The model's index: digests to labels. A digest that includes my own
    label is my own sentence; another skill's label is a duplicate."""
    from thalovant_skillkit.model import Row, sentence_index

    rows = [Row("will it rain", "weather:rain", "en-US"),
            Row("will it rain", "pulse:pulse", "en-US"),
            Row("water the garden", "pulse:pulse", "en-US"),
            Row("va-t-il pleuvoir", "weather:rain", "fr-FR")]
    index = sentence_index(rows)
    assert index["version"] == 1
    assert len(index["labels"]) == 3
    def line(lang, number, text):
        return intents.IntentLine("pulse", "pulse", lang, "p.intent", number, text, text)

    mine = [line("en-US", 1, "will it rain"), line("en-US", 2, "water the garden"),
            line("fr-FR", 1, "will it rain")]
    found = fleet.find_indexed_duplicates(mine, index, "pulse")
    assert [(f.mine.line, f.theirs.skill, f.theirs.intent) for f in found] == [
        (1, "weather", "rain")]
    assert found[0].fails and "fleet index" in found[0].describe()
    # the same text in another language is another sentence
    assert fleet.find_indexed_duplicates(mine[2:], index, "pulse") == []


def test_resolve_model_takes_a_directory_first(tmp_path: Path):
    assert fleet.resolve_model(str(tmp_path)) == tmp_path


def test_check_with_a_model_directory_uses_its_index(tmp_path: Path, monkeypatch):
    pytest.importorskip("model2vec.inference")
    from thalovant_skillkit.model import Row, sentence_index

    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "index.json").write_text(json.dumps(sentence_index(
        [Row("will it rain", "thalovant-skill-weather.thalovant:rain", "en-US")])))
    # no classifier: keep the predicted check out of this test
    monkeypatch.setattr(fleet, "find_predicted", lambda *a, **k: [])
    new = _skill(tmp_path / "new", "pulse", {"en-US/pulse.intent": "will it rain\nwater it\n"})
    findings, notes = fleet.check_fleet(new, model=str(model_dir))
    assert [(f.kind, f.mine.text, f.theirs.skill) for f in findings] == [
        ("duplicate", "will it rain", "thalovant-skill-weather.thalovant")]
    assert notes == []
