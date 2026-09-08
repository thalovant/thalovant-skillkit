"""Does this skill publish a sentence another skill already owns?

A skill's own suite loads one skill, so it cannot see that "will it rain" is
also weather's, and that a real core with both loaded gives it to weather.
This module compares a skill with the rest of the fleet and says, per line of
the skill's own files, what it found.

Two sources, one public and one not. The fleet's model on the Hugging Face
Hub (`thalovant/thalovant-m2v-intents`, built by `thalovant/intent-corpus`)
ships an index of every sentence's digest and the classifier itself, so a
skill's CI needs nothing private: `check`. The fleet corpus (see
`intents.py`) has the sentences and their lines, for a fleet checkout:
`check --fleet`.

Five kinds of finding, with different weight:

* `duplicate` -- the same sentence, another skill, and this skill does not
  publish it in the fleet's own record yet. One core, one owner: the line
  here or the line there never fires. This change introduces it, so this
  fails the check.
* `known` -- the same sentence, another skill, and the fleet's record
  already has both. Someone should still resolve it, but this change did
  not cause it, so it does not fail. Once resolved it cannot come back:
  the record drops it, and a line that re-adds it is a `duplicate` again.
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

import json
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
    sentence_key,
)

#: The fleet's model on the Hugging Face Hub: what a skill compares itself with.
MODEL_ID = "thalovant/thalovant-m2v-intents"
#: The embedding model behind the paraphrase check (corpus checkouts only).
MODEL = "Jarbas/ovos-model2vec-intents-distiluse-base-multilingual-cased-v2"
NEAR_THRESHOLD = 0.85
PREDICTED_THRESHOLD = 0.9


@dataclass(frozen=True)
class Collision:
    kind: str  # duplicate | known | self | near | predicted
    mine: IntentLine
    theirs: IntentLine
    score: float

    @property
    def fails(self) -> bool:
        return self.kind == "duplicate"

    def describe(self) -> str:
        where = f"{self.theirs.file}:{self.theirs.line}" if self.theirs.file else "fleet index"
        if self.kind == "duplicate":
            return (f'"{self.mine.text}" is already {self.theirs.skill}\'s {self.theirs.intent} '
                    f"({where}); one core, one owner -- drop it here or agree on who answers")
        if self.kind == "known":
            return (f'"{self.mine.text}" is also {self.theirs.skill}\'s {self.theirs.intent} '
                    f"({where}); the fleet already carries both, so this change did not cause "
                    f"it -- one of the two skills never answers this")
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


def find_duplicates(mine: list[IntentLine], others: list[IntentLine],
                    already: set[str] | None = None) -> list[Collision]:
    """Sentences another skill publishes. `already` is what this skill
    publishes in the fleet's own record: a collision on one of those is
    older than this change, and is reported without failing."""
    by_text: dict[str, IntentLine] = {}
    for line in others:
        by_text.setdefault(line.text, line)
    already = already or set()
    return [Collision("known" if line.text in already else "duplicate",
                      line, by_text[line.text], 1.0)
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


def find_indexed_duplicates(mine: list[IntentLine], index: dict, skill_id: str) -> list[Collision]:
    """Exact duplicates by digest, against the index the fleet's model ships.

    A sentence the index already lists under this skill's own label is a
    collision the fleet has been carrying; this change did not introduce it,
    so it is reported without failing.
    """
    labels: dict[str, list[str]] = index.get("labels") or {}
    out: list[Collision] = []
    for line in mine:
        published = labels.get(sentence_key(line.lang, line.text), [])
        owners = [label for label in published if label.partition(":")[0] != skill_id]
        if not owners:
            continue
        mine_already = len(owners) < len(published)
        owner, _, intent = owners[0].partition(":")
        theirs = IntentLine(owner, intent, line.lang, "", 0, "", "")
        out.append(Collision("known" if mine_already else "duplicate", line, theirs, 1.0))
    return out


class ModelUnavailable(OSError):
    """The fleet's model could not be fetched: offline, or not published yet."""


def resolve_model(model: str) -> Path:
    """A local model directory, or a Hub repository fetched into the cache."""
    path = Path(model)
    if path.is_dir():
        return path
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import HfHubHTTPError, RepositoryNotFoundError

    try:
        return Path(snapshot_download(repo_id=model))
    except (RepositoryNotFoundError, HfHubHTTPError, OSError) as failure:
        raise ModelUnavailable(f"model {model!r} is neither a directory nor a Hub repository "
                               f"this machine can fetch: {failure}") from failure


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


def model_check_available() -> bool:
    try:
        from model2vec.inference import StaticModelPipeline  # noqa: F401
    except ImportError:
        return False
    return True


def check_fleet(skill_root: Path, corpus_dir: Path | None = None, *, near: bool = True,
                threshold: float = NEAR_THRESHOLD,
                model: str | None = None) -> tuple[list[Collision], list[str]]:
    """Compare a skill with the fleet: with the corpus (sentences and lines),
    with the published model (its sentence index and its classifier), or
    both. Every language the skill declares is compared.

    Returns the findings and the notes a person should read alongside them
    (languages with no corpus, a check skipped for a missing extra).
    """
    skill_root = Path(skill_root)
    skill_id, locale_dir = skill_identity(skill_root)
    findings: list[Collision] = []
    notes: list[str] = []
    run_near = corpus_dir is not None and near and near_check_available()
    if corpus_dir is not None and near and not run_near:
        notes.append("near-duplicate check skipped: install thalovant-skillkit[fleet]")
    index: dict = {}
    model_dir: Path | None = None
    if model is not None:
        if not model_check_available():
            notes.append("classifier check skipped: install thalovant-skillkit[fleet]")
        else:
            model_dir = resolve_model(model)
            index_path = model_dir / "index.json"
            if index_path.is_file():
                index = json.loads(index_path.read_text(encoding="utf-8"))
            else:
                notes.append(f"{model}: no index.json, exact duplicates not checked against it")
    for lang in locale_langs(locale_dir):
        mine = intent_lines(skill_root, locale_dir, lang, skill_id)
        if not mine:
            continue
        findings.extend(find_self_duplicates(mine))
        if index:
            findings.extend(find_indexed_duplicates(mine, index, skill_id))
        if model_dir is not None:
            findings.extend(find_predicted(mine, model_dir, skill_id))
        if corpus_dir is None:
            continue
        path = Path(corpus_dir) / f"{lang}.json"
        if not path.is_file():
            notes.append(f"{lang}: no fleet corpus, only this skill's own files compared")
            continue
        recorded = corpus_lines(load_corpus(path))
        others = [line for line in recorded if line.skill != skill_id]
        already = {line.text for line in recorded if line.skill == skill_id}
        found = find_duplicates(mine, others, already)
        seen = {(f.mine.file, f.mine.line, f.mine.text)
                for f in findings if f.kind in ("duplicate", "known")}
        findings.extend(f for f in found if (f.mine.file, f.mine.line, f.mine.text) not in seen)
        if run_near:
            findings.extend(find_near(mine, others, threshold))
    return findings, notes


def render(collision: Collision) -> str:
    """One line for a terminal, or a GitHub annotation that lands on the line
    of the intent file when running under Actions."""
    text = collision.describe()
    if os.environ.get("GITHUB_ACTIONS"):
        level = "error" if collision.fails else "warning"
        return f"::{level} file={collision.mine.file},line={collision.mine.line}::{text}"
    return f"{collision.mine.file}:{collision.mine.line}: {text}"
