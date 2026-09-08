"""The Thalovant intent classifier: a model2vec model trained on the fleet corpus.

OpenVoiceOS ships `ovos-m2v-intents-*` models for its own skills: static
embeddings and a small classifier head that maps an utterance to a label of
the form `<skill_id>:<intent>`, which `ovos-m2v-pipeline` then routes like a
padatious match. This module builds the same kind of model from the Thalovant
fleet corpus (see `intents.py`) and nothing else, so its label set is exactly
the intents the hub's skills register.

Training is model2vec's own trainer (embeddings fine-tuned, two-layer head,
early stopping on a validation split), so the result loads with
`StaticModelPipeline.from_pretrained` and drops into the pipeline's
`classifier` mode. Beside the weights it writes `labels.json` the way the
OVOS models do, and `training.json` with the held-out accuracy per language
and every confusion the classifier made -- which is the fleet's collision list
as a trained classifier sees it, the closest thing to padatious short of
booting a core.

    thalovant-skillkit model corpus/ --out model/

Needs `thalovant-skillkit[model]` (torch and scikit-learn).
"""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from thalovant_skillkit.intents import corpus_lines, load_corpus, sentence_key

BASE_MODEL = "Jarbas/m2v-256-distiluse-base-multilingual-cased-v2"
#: Where the fleet's model lives; what a skill's CI compares itself with.
MODEL_ID = "thalovant/thalovant-m2v-intents"
SEED = 42
INDEX_VERSION = 1


@dataclass(frozen=True)
class Row:
    text: str
    label: str
    lang: str


def training_rows(corpus_dir: Path) -> tuple[list[Row], dict]:
    """Every sentence of every language, labelled `skill_id:intent`, and the
    corpus metadata (skills, commits, build times) that produced it."""
    rows: list[Row] = []
    meta: dict = {"languages": {}, "skills": {}}
    for path in sorted(Path(corpus_dir).glob("*.json")):
        corpus = load_corpus(path)
        lines = corpus_lines(corpus)
        seen: set[tuple[str, str]] = set()
        for line in lines:
            key = (line.text, line.skill + ":" + line.intent)
            if key in seen:
                continue
            seen.add(key)
            rows.append(Row(line.text, f"{line.skill}:{line.intent}", corpus["lang"]))
        meta["languages"][corpus["lang"]] = {"built": corpus["built"], "sentences": len(lines)}
        meta["skills"].update(corpus["skills"])
    return rows, meta


def split(rows: list[Row], test_size: float = 0.2, seed: int = SEED) -> tuple[list[Row], list[Row]]:
    """A held-out share per label, so every intent is judged on sentences it
    was not trained on. Every label keeps at least one training sentence, so
    the model knows every label `labels.json` will advertise; every label
    with two or more sentences gives up at least one, so every label is
    judged. A label with a single sentence stays in training."""
    if not 0 <= test_size < 1:
        raise ValueError(f"test_size must be in [0, 1), got {test_size}")
    by_label: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        by_label[row.label].append(row)
    rng = random.Random(seed)
    train: list[Row] = []
    test: list[Row] = []
    for label in sorted(by_label):
        group = list(by_label[label])
        rng.shuffle(group)
        held = 0
        if test_size > 0 and len(group) >= 2:
            held = min(max(1, int(round(len(group) * test_size))), len(group) - 1)
        test.extend(group[:held])
        train.extend(group[held:])
    return train, test


def train(rows: list[Row], base: str = BASE_MODEL, *, max_epochs: int = -1,
          patience: int = 5, seed: int = SEED):
    """model2vec's classifier trainer over the base static model."""
    from model2vec.train import StaticModelForClassification

    model = StaticModelForClassification.from_pretrained(path=base)
    model.fit([r.text for r in rows], [r.label for r in rows], max_epochs=max_epochs,
              early_stopping_patience=patience, random_seed=seed)
    return model


def evaluate(model, rows: list[Row]) -> dict:
    """Held-out accuracy overall and per language, and the confusions.

    A confusion is a true label the classifier gave to another label, with how
    often and an example: `weather:current.weather` predicted as
    `local-pulse:local.pulse` is the local-pulse duplicate seen from the
    model's side.
    """
    if not rows:
        return {"rows": 0, "accuracy": None, "per_language": {}, "confusions": []}
    predicted = [str(p) for p in model.predict([r.text for r in rows])]
    correct = 0
    per_lang: dict[str, Counter] = defaultdict(Counter)
    confusions: dict[tuple[str, str], dict] = {}
    for row, guess in zip(rows, predicted, strict=True):
        hit = guess == row.label
        correct += hit
        per_lang[row.lang]["rows"] += 1
        per_lang[row.lang]["correct"] += hit
        if not hit:
            entry = confusions.setdefault((row.label, guess), {
                "true": row.label, "predicted": guess, "count": 0, "examples": []})
            entry["count"] += 1
            if len(entry["examples"]) < 3:
                entry["examples"].append({"text": row.text, "lang": row.lang})
    return {
        "rows": len(rows),
        "accuracy": round(correct / len(rows), 4),
        "per_language": {
            lang: {"rows": c["rows"], "accuracy": round(c["correct"] / c["rows"], 4)}
            for lang, c in sorted(per_lang.items())
        },
        "confusions": sorted(confusions.values(), key=lambda e: -e["count"]),
    }


def sentence_index(rows: list[Row]) -> dict:
    """Every sentence in the corpus as a digest, with the labels that publish
    it. Ships beside the model so a skill can check for exact duplicates
    against the whole fleet from the public model alone."""
    labels: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        key = sentence_key(row.lang, row.text)
        if row.label not in labels[key]:
            labels[key].append(row.label)
    return {"version": INDEX_VERSION, "key": "sha256(lang + newline + text)",
            "labels": dict(sorted(labels.items()))}


def _model_card(name: str, base: str, labels: list[str], report: dict, meta: dict) -> str:
    langs = report["per_language"]
    table = "\n".join(
        f"| `{lang}` | {stats['rows']} | {stats['accuracy']:.4f} |"
        for lang, stats in langs.items() if stats["rows"] >= 20
    )
    top = "\n".join(
        f"- `{c['true']}` read as `{c['predicted']}` ({c['count']}): "
        f"\"{c['examples'][0]['text']}\" ({c['examples'][0]['lang']})"
        for c in report["confusions"][:15]
    ) or "- none"
    accuracy = f"{report['accuracy']:.4f}" if report["accuracy"] is not None else "n/a"
    return f"""---
license: apache-2.0
library_name: model2vec
base_model: {base}
tags: [model2vec, text-classification, intent-classification, ovos, thalovant]
pipeline_tag: text-classification
---

# {name}

A static-embedding intent classifier for the Thalovant hub. It maps an
utterance to one of {len(labels)} labels of the form `<skill_id>:<intent>`,
exactly as `ovos-m2v-pipeline` registers them, and it knows only the
Thalovant skills: every label comes from the fleet corpus and nothing else.

Base: [{base}](https://huggingface.co/{base}), fine-tuned with model2vec's
classifier trainer. Held-out accuracy {accuracy} over {report['rows']} rows
across {len(langs)} languages.

## Use

```python
from model2vec.inference import StaticModelPipeline

model = StaticModelPipeline.from_pretrained("{name}")
model.predict(["will it rain tomorrow"])
```

Configure the pipeline with `"mode": "classifier"` and this model's path;
`labels.json` beside the weights lists the labels the hub may route to.

`index.json` names every sentence in the training corpus by a digest of its
language and text, with the labels that publish it. `thalovant-skillkit check
--model {name}` uses it to fail a skill that publishes a sentence another
skill already owns, and asks this classifier what it makes of the rest --
without the fleet's sentences leaving their private repositories.

## Held-out accuracy per language

| Language | Rows | Accuracy |
|---|---:|---:|
{table}

## What the classifier confuses

Each line is a sentence whose true intent the classifier read as another
intent. Two skills on one line is a collision the fleet should resolve.

{top}

Trained from the corpus built {meta.get('built', 'unknown')} covering
{len(meta.get('skills', {}))} skills.
"""


def build(corpus_dir: Path, out_dir: Path, *, base: str = BASE_MODEL,
          name: str = MODEL_ID, test_size: float = 0.2,
          max_epochs: int = -1, seed: int = SEED, corpus_commit: str = "") -> dict:
    """Train, evaluate, and write the model directory. Returns the report.

    `corpus_commit` is the commit of the corpus checkout, recorded in
    `training.json` so a rebuild can tell whether the published model is
    behind the corpus without retraining to find out."""
    rows, meta = training_rows(corpus_dir)
    meta["commit"] = corpus_commit
    if not rows:
        raise ValueError(f"no corpus under {corpus_dir}")
    train_rows, test_rows = split(rows, test_size, seed)
    model = train(train_rows, base, max_epochs=max_epochs, seed=seed)
    report = evaluate(model, test_rows)
    labels = sorted({r.label for r in rows})
    built = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    meta["built"] = built

    out_dir = Path(out_dir)
    pipeline = model.to_pipeline()
    pipeline.save_pretrained(str(out_dir))
    (out_dir / "labels.json").write_text(
        json.dumps({"valid_labels": labels}, indent=2) + "\n", encoding="utf-8")
    (out_dir / "index.json").write_text(
        json.dumps(sentence_index(rows), indent=0) + "\n", encoding="utf-8")
    (out_dir / "training.json").write_text(json.dumps({
        "name": name, "base": base, "built": built, "seed": seed,
        "rows": {"total": len(rows), "train": len(train_rows), "test": len(test_rows)},
        "labels": len(labels), "corpus": meta, "report": report,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    card = _model_card(name, base, labels, report, meta)
    (out_dir / "README.md").write_text(card, encoding="utf-8")
    return report
