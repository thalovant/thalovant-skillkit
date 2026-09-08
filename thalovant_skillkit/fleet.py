"""Does this skill publish a sentence another skill already owns?

A skill's own suite loads one skill, so it cannot see that "will it rain" is
also weather's, and that a real core with both loaded gives it to weather. The
fleet corpus (see `intents.py`) is every other skill's sentences; this module
compares a skill against it and says, per line of the skill's own files, what
it found.

Three kinds of finding, with different weight:

* `duplicate` -- the same sentence, another skill. One core, one owner: the
  line here or the line there never fires. This fails the check.
* `self` -- the same sentence in two of this skill's own intents. Padatious
  picks one and the other is dead for that sentence. Reported, not failed.
* `near` -- a close paraphrase in another skill, by the embedding model the
  OVOS model2vec pipeline uses for intents. Measured against a real core,
  near pairs mostly route correctly (padatious weighs the one word that
  differs), so this is a warning: two authors should look.
* `predicted` -- the fleet's own classifier (`thalovant-m2v-intents`, trained
  on every other skill) reads the sentence as another skill's with high
  confidence. Measured on a skill held out of training, a sentence that
  really competes scores above 0.9 ("tell me a fart fact" is joke-garden's
  at 1.00) and a genuinely new one does not ("pull my finger", 0.06). A
  warning: on the hub's m2v pipeline, that other skill would answer.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from thalovant_skillkit.checks import _entry_points, find_package
from thalovant_skillkit.intents import (
    IntentLine,
    corpus_lines,
    intent_lines,
    load_corpus,
    locale_langs,
)

MODEL = "Jarbas/ovos-model2vec-intents-distiluse-base-multilingual-cased-v2"
NEAR_THRESHOLD = 0.85
PREDICTED_THRESHOLD = 0.9


@dataclass(frozen=True)
class Collision:
    kind: str  # duplicate | self | near | predicted
    mine: IntentLine
    theirs: IntentLine
    score: float

    @property
    def fails(self) -> bool:
        return self.kind == "duplicate"

    def describe(self) -> str:
        where = f"{self.theirs.file}:{self.theirs.line}"
        if self.kind == "duplicate":
            return (f'"{self.mine.text}" is already {self.theirs.skill}\'s {self.theirs.intent} '
                    f"({where}); one core, one owner -- drop it here or agree on who answers")
        if self.kind == "self":
            return (f'"{self.mine.text}" is also this skill\'s {self.theirs.intent} '
                    f"({where}); padatious picks one and the other never fires for it")
        if self.kind == "predicted":
            return (f'"{self.mine.text}" reads as {self.theirs.skill}\'s {self.theirs.intent} '
                    f"to the fleet's classifier ({self.score:.2f}); on the hub's m2v pipeline "
                    f"that skill would answer it -- worth a look together")
        return (f'"{self.mine.text}" is {self.score:.2f} like {self.theirs.skill}\'s '
                f'{self.theirs.intent} "{self.theirs.text}" ({where}); '
                f"a user's own wording may reach either -- worth a look together")


def skill_identity(skill_root: Path) -> tuple[str, Path]:
    """The skill id the hub knows this skill by, and its locale directory."""
    package = find_package(skill_root)
    if package is None:
        raise ValueError(f"{skill_root}: no skill package found")
    specs = _entry_points(skill_root)
    skill_id = specs[0].split("=", 1)[0].strip() if specs else package.name
    return skill_id, package / "locale"


def own_lines(skill_root: Path, lang: str) -> list[IntentLine]:
    skill_id, locale_dir = skill_identity(skill_root)
    return intent_lines(skill_root, locale_dir, lang, skill_id)


def find_duplicates(mine: list[IntentLine], others: list[IntentLine]) -> list[Collision]:
    by_text: dict[str, IntentLine] = {}
    for line in others:
        by_text.setdefault(line.text, line)
    return [Collision("duplicate", line, by_text[line.text], 1.0)
            for line in mine if line.text in by_text]


def find_self_duplicates(mine: list[IntentLine]) -> list[Collision]:
    first: dict[str, IntentLine] = {}
    out: list[Collision] = []
    for line in mine:
        earlier = first.setdefault(line.text, line)
        if earlier is not line and earlier.intent != line.intent:
            out.append(Collision("self", line, earlier, 1.0))
    return out


def find_near(mine: list[IntentLine], others: list[IntentLine],
              threshold: float = NEAR_THRESHOLD) -> list[Collision]:
    """Closest other-skill sentence per line of mine, above the threshold.
    Exact matches are the duplicate check's business and are skipped here."""
    if not mine or not others:
        return []
    import numpy as np
    from model2vec import StaticModel

    model = StaticModel.from_pretrained(MODEL)

    def unit(texts: list[str]):
        vectors = model.encode(texts).astype("float32")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    theirs = unit([line.text for line in others])
    out: list[Collision] = []
    block = 1024
    for start in range(0, len(mine), block):
        chunk = mine[start:start + block]
        sims = unit([line.text for line in chunk]) @ theirs.T
        for line, row in zip(chunk, sims, strict=True):
            j = int(np.argmax(row))
            score = float(row[j])
            if score >= threshold and others[j].text != line.text:
                out.append(Collision("near", line, others[j], score))
    return out


def find_predicted(mine: list[IntentLine], model_dir: Path, skill_id: str,
                   threshold: float = PREDICTED_THRESHOLD) -> list[Collision]:
    """What the fleet's trained classifier makes of each of my sentences."""
    if not mine:
        return []
    import numpy as np
    from model2vec.inference import StaticModelPipeline

    pipeline = StaticModelPipeline.from_pretrained(str(model_dir))
    classes = np.asarray(pipeline.classes_)
    proba = pipeline.predict_proba([line.text for line in mine])
    out: list[Collision] = []
    for line, row in zip(mine, proba, strict=True):
        j = int(np.argmax(row))
        label, score = str(classes[j]), float(row[j])
        owner, _, intent = label.partition(":")
        if owner != skill_id and score >= threshold:
            theirs = IntentLine(owner, intent, line.lang, "", 0, "", "")
            out.append(Collision("predicted", line, theirs, score))
    return out


def near_check_available() -> bool:
    try:
        import model2vec  # noqa: F401
    except ImportError:
        return False
    return True


def check_fleet(skill_root: Path, corpus_dir: Path, *, near: bool = True,
                threshold: float = NEAR_THRESHOLD,
                model_dir: Path | None = None) -> tuple[list[Collision], list[str]]:
    """Compare a skill with the fleet corpus, every language both sides have,
    and with the fleet's classifier when a model directory is given.

    Returns the findings and the notes a person should read alongside them
    (languages with no corpus, the near check skipped).
    """
    skill_root = Path(skill_root)
    skill_id, locale_dir = skill_identity(skill_root)
    findings: list[Collision] = []
    notes: list[str] = []
    run_near = near and near_check_available()
    if near and not run_near:
        notes.append("near-duplicate check skipped: install thalovant-skillkit[fleet]")
    run_model = model_dir is not None and near_check_available()
    if model_dir is not None and not run_model:
        notes.append("classifier check skipped: install thalovant-skillkit[fleet]")
    for lang in locale_langs(locale_dir):
        mine = intent_lines(skill_root, locale_dir, lang, skill_id)
        if not mine:
            continue
        findings.extend(find_self_duplicates(mine))
        path = Path(corpus_dir) / f"{lang}.json"
        if not path.is_file():
            notes.append(f"{lang}: no fleet corpus, only this skill's own files compared")
            continue
        others = [line for line in corpus_lines(load_corpus(path)) if line.skill != skill_id]
        findings.extend(find_duplicates(mine, others))
        if run_near:
            findings.extend(find_near(mine, others, threshold))
        if run_model:
            findings.extend(find_predicted(mine, Path(model_dir), skill_id))
    return findings, notes


def render(collision: Collision) -> str:
    """One line for a terminal, or a GitHub annotation that lands on the line
    of the intent file when running under Actions."""
    text = collision.describe()
    if os.environ.get("GITHUB_ACTIONS"):
        level = "error" if collision.fails else "warning"
        return f"::{level} file={collision.mine.file},line={collision.mine.line}::{text}"
    return f"{collision.mine.file}:{collision.mine.line}: {text}"
