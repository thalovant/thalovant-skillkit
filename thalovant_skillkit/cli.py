"""`thalovant-skillkit new`, `check` and `corpus`.

Starting a skill used to mean copying an existing one and deleting what did not
apply, which carried its plumbing along -- and its mistakes. `new` writes a
complete skill that passes its own tests, with the conventions the fleet's CI
expects already in place. `check` runs those same checks on any skill, and with
`--fleet` also asks whether a sentence this skill publishes already belongs to
another one. `corpus` writes the fleet corpus that `--fleet` reads.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from .checks import check_all, find_package
from .model import MODEL_ID
from .version import __version__

# Pinned by commit, as every workflow in the fleet is.
CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
SETUP_PYTHON = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0"


def _names(raw: str) -> dict[str, str]:
    """Every spelling of the skill's name, from the one the person typed."""
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    slug = slug.removeprefix("thalovant-skill-").removeprefix("skill-")
    if not slug:
        raise SystemExit(f"cannot make a skill name out of {raw!r}")
    words = slug.split("-")
    return {
        "slug": slug,                                   # news
        "repo": f"thalovant-skill-{slug}",              # thalovant-skill-news
        "package": f"thalovant_skill_{slug.replace('-', '_')}",  # thalovant_skill_news
        "clazz": "".join(w.capitalize() for w in words) + "Skill",  # NewsSkill
        "title": " ".join(w.capitalize() for w in words),           # News
        "keyword": "".join(w.capitalize() for w in words) + "Keyword",  # NewsKeyword
        "dialog": slug.replace("-", "."),               # news
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.lstrip("\n"), encoding="utf-8")


def scaffold(root: Path, names: dict[str, str], priority: int) -> list[Path]:
    """Write a complete skill under `root`. Returns what was written."""
    n = names
    written: list[Path] = []

    def put(relative: str, text: str) -> None:
        path = root / relative
        _write(path, text)
        written.append(path)

    put(f"{n['package']}/__init__.py", f'''
"""{n['title']}: a Thalovant skill."""
from thalovant_skillkit.skill import ThalovantFallbackSkill


class {n['clazz']}(ThalovantFallbackSkill):
    # Where this skill sits in the fallback ladder. The hub asks fallback skills
    # in order and stops at the first that says yes: 91-95 answer one specific
    # thing, 96-98 a topic, 99-100 almost anything. A skill that claims broadly
    # from low in the ladder silences every skill behind it.
    FALLBACK_PRIORITY = {priority}

    def can_answer(self, message) -> bool:
        """Cheap and narrow: this runs for everything anyone says."""
        return self.mentions(self.utterance(message), "{n['keyword']}", self.lang_of(message))

    def reply(self, utterance: str, lang: str, context: dict) -> str | None:
        """The answer as text. Spoken on the hub, shown in the showroom."""
        return self.dialog("{n['dialog']}", lang)
''')

    put(f"{n['package']}/version.py", '__version__ = "0.1.0"\n')

    put(f"{n['package']}/locale/supported.json",
        json.dumps({"locales": ["en-US", "fr-FR"]}, indent=2) + "\n")

    for lang, vocab, dialog, name in (
        ("en-US", f"{n['slug'].replace('-', ' ')}\n",
         f"This is the {n['title']} skill.\n", n["title"]),
        ("fr-FR", f"{n['slug'].replace('-', ' ')}\n",
         f"Voici la compétence {n['title']}.\n", n["title"]),
    ):
        put(f"{n['package']}/locale/{lang}/vocab/{n['keyword']}.voc", vocab)
        put(f"{n['package']}/locale/{lang}/dialog/{n['dialog']}.dialog", dialog)
        put(f"{n['package']}/locale/{lang}/skill.json", json.dumps({
            "skill_id": n["repo"], "name": name,
            "source": f"https://github.com/thalovant/{n['repo']}",
        }, indent=2) + "\n")

    put("test/test_skill.py", f'''
from thalovant_skillkit.testing import message

from {n['package']} import {n['clazz']}


def test_it_hears_its_keyword():
    assert {n['clazz']}().can_answer(message("tell me about {n['slug'].replace('-', ' ')}"))


def test_it_hears_it_in_french():
    assert {n['clazz']}().can_answer(message("{n['slug'].replace('-', ' ')}", lang="fr-FR"))


def test_it_ignores_what_is_not_its_business():
    """Write this one first. A skill that answers too much fails silently:
    nothing breaks, another skill just stops being heard."""
    assert not {n['clazz']}().can_answer(message("set a timer for ten minutes"))


def test_it_has_something_to_say():
    assert {n['clazz']}().preview_reply("{n['slug'].replace('-', ' ')}", "en-US")
''')

    put("test/test_contract.py", '''
"""The checks every Thalovant skill keeps: locales complete, packaging sound."""
from pathlib import Path

from thalovant_skillkit.checks import check_all


def test_the_skill_keeps_its_contracts():
    assert check_all(Path(__file__).parents[1]) == []
''')

    put("pyproject.toml", f'''
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "{n['repo']}"
description = "{n['title']}: a Thalovant skill"
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"
dynamic = ["version"]
dependencies = [
    "thalovant-skillkit[skill]>={__version__}",
]

[project.optional-dependencies]
test = ["pytest", "thalovant-skillkit[fleet]"]

[project.entry-points."opm.skill"]
"{n['repo']}.thalovant" = "{n['package']}:{n['clazz']}"

[tool.setuptools]
packages = ["{n['package']}"]

# The locale tree ships in the wheel. Without this the installed skill has no
# dialog files and answers with their names.
[tool.setuptools.package-data]
{n['package']} = ["locale/*.json", "locale/*/*", "locale/*/*/*"]

[tool.setuptools.dynamic]
version = {{ attr = "{n['package']}.version.__version__" }}
''')

    put(".github/workflows/test.yml", f'''
permissions:
  contents: read

name: Test

on:
  pull_request:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: {CHECKOUT}
      - uses: {SETUP_PYTHON}
        with:
          python-version: "3.12"
      - run: python -m pip install -e ".[test]"
      - run: thalovant-skillkit check
      - run: pytest -q

      # Every skill's intents are trained into one classifier on the hub, so a
      # sentence this skill publishes must not already be another skill's. The
      # fleet's model on the Hugging Face Hub carries an index of every sentence
      # and the classifier itself: the check fails on an exact duplicate,
      # annotated on the line, and warns on a sentence the classifier reads as
      # another skill's. Public model, nothing private needed.
      - name: Check against the fleet
        run: thalovant-skillkit check --model {MODEL_ID}

      # After a merge, ask the corpus to pick up this skill's sentences, so the
      # next skill is checked against this one. CROSS_REPO_TOKEN is the org
      # secret for private repositories; without it this step only says so.
      - name: Tell the corpus a skill changed
        if: github.event_name == 'push' && github.ref == 'refs/heads/main'
        env:
          GH_TOKEN: ${{{{ secrets.CROSS_REPO_TOKEN }}}}
        run: |
          if [ -z "$GH_TOKEN" ]; then
            echo "::warning::CROSS_REPO_TOKEN is not exposed here; the corpus was not told"
            exit 0
          fi
          gh api repos/thalovant/intent-corpus/dispatches -f event_type=skill-merged
''')

    put("README.md", f'''
# {n['repo']}

{n['title']}: a Thalovant skill.

```bash
pip install -e ".[test]"
thalovant-skillkit check
pytest
```

Say what it answers in `{n['package']}/locale/<lang>/vocab/{n['keyword']}.voc`,
how it replies in `locale/<lang>/dialog/{n['dialog']}.dialog`, and the rest in
`{n['package']}/__init__.py`.

Guide: https://docs.thalovant.com/developers/writing-a-skill
''')

    put(".gitignore", '''
__pycache__/
*.py[cod]
*.egg-info/
build/
dist/
.pytest_cache/
.venv/
''')
    return written


def cmd_new(args: argparse.Namespace) -> int:
    names = _names(args.name)
    root = Path(args.directory or names["repo"])
    if root.exists() and any(root.iterdir()):
        print(f"{root} exists and is not empty; choose another --directory", file=sys.stderr)
        return 2
    written = scaffold(root, names, args.priority)
    print(f"{names['repo']}: {len(written)} files under {root}/")
    for path in written:
        print(f"  {path.relative_to(root)}")
    print()
    print("Next:")
    print(f"  cd {root}")
    print('  pip install -e ".[test]"')
    print("  thalovant-skillkit check && pytest")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.directory or ".").resolve()
    problems = check_all(root)
    if problems:
        print(f"{len(problems)} problem(s) in {root.name}:")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print(f"ok: {root.name} keeps its contracts")
    failed = bool(problems)

    if args.fleet is not None or args.model is not None:
        from .fleet import check_fleet, render

        corpus_dir = Path(args.fleet) if args.fleet else None
        try:
            findings, notes = check_fleet(root, corpus_dir, near=not args.no_near,
                                          threshold=args.threshold, model=args.model)
        except (ValueError, OSError) as failure:
            # No package, no locale tree, no corpus, no model: the contract
            # checks above already said which; a traceback adds nothing.
            print(f"fleet check did not run: {failure}")
            return 1
        for note in notes:
            print(f"note: {note}")
        for finding in sorted(findings, key=lambda f: (not f.fails, f.mine.file, f.mine.line)):
            print(render(finding))
        blocking = sum(1 for f in findings if f.fails)
        if blocking:
            print(f"{blocking} sentence(s) already belong to another skill")
            failed = True
        elif findings:
            print(f"ok: nothing another skill owns; {len(findings)} thing(s) worth a look above")
        else:
            print("ok: nothing another skill owns")
    return 1 if failed else 0


def _git(root: Path, *argv: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *argv], check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def cmd_model(args: argparse.Namespace) -> int:
    """Train the Thalovant intent classifier from a corpus directory."""
    from .model import BASE_MODEL, build

    report = build(Path(args.corpus), Path(args.out), base=args.base or BASE_MODEL, name=args.name,
                   test_size=args.test_size, max_epochs=args.max_epochs)
    print(f"held-out accuracy {report['accuracy']} over {report['rows']} rows, "
          f"{len(report['per_language'])} languages; {len(report['confusions'])} confusion(s)")
    for confusion in report["confusions"][:10]:
        example = confusion["examples"][0]
        print(f"  {confusion['count']:3}  {confusion['true']} read as {confusion['predicted']}"
              f"  e.g. {example['text']!r} ({example['lang']})")
    print(f"wrote {Path(args.out).resolve()}")
    return 0


def cmd_corpus(args: argparse.Namespace) -> int:
    """Write the fleet corpus from a directory of skill checkouts."""
    from .fleet import skill_identity
    from .intents import build_corpus, locale_langs, write_corpus

    root = Path(args.directory).resolve()
    skills = []
    for checkout in sorted(p for p in root.iterdir() if p.is_dir()):
        if find_package(checkout) is None:
            continue
        skill_id, locale_dir = skill_identity(checkout)
        if not locale_dir.is_dir():
            continue
        metadata = {"repo": _git(checkout, "remote", "get-url", "origin"),
                    "sha": _git(checkout, "rev-parse", "HEAD")}
        skills.append((skill_id, checkout, locale_dir, metadata))
    if not skills:
        print(f"no skills under {root}", file=sys.stderr)
        return 2
    langs = args.lang or sorted({lang for _, _, locale_dir, _ in skills
                                 for lang in locale_langs(locale_dir)})
    out = Path(args.out).resolve()
    for lang in langs:
        corpus = build_corpus(skills, lang)
        if not corpus["lines"]:
            continue
        path = write_corpus(out, corpus)
        print(f"{path.name}: {len(corpus['lines'])} sentences from {len(corpus['skills'])} skills")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="thalovant-skillkit",
                                     description="Write and check Thalovant skills.")
    parser.add_argument("--version", action="version", version=f"thalovant-skillkit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="write a complete new skill")
    new.add_argument("name", help='the skill, e.g. "news" or "thalovant-skill-news"')
    new.add_argument("--directory", help="where to write it (default: ./thalovant-skill-<name>)")
    new.add_argument("--priority", type=int, default=98,
                     help="fallback rung, 91-100 (default 98: answers a topic)")
    new.set_defaults(func=cmd_new)

    check = sub.add_parser("check", help="check a skill's locales and packaging")
    check.add_argument("directory", nargs="?", help="the skill (default: here)")
    check.add_argument("--model", metavar="ID|DIR", nargs="?", const=MODEL_ID,
                       help="compare with the fleet's published model (default "
                            f"{MODEL_ID}): fail on a sentence its index says another skill "
                            "publishes, warn on one its classifier reads as another skill's")
    check.add_argument("--fleet", metavar="DIR",
                       help="directory of fleet corpus files (<lang>.json): the same, with the "
                            "other skill's file and line, plus close paraphrases")
    check.add_argument("--no-near", action="store_true",
                       help="with --fleet: no paraphrase check, no embedding model")
    check.add_argument("--threshold", type=float, default=0.85,
                       help="with --fleet: similarity at which a paraphrase is reported (0.85)")
    check.set_defaults(func=cmd_check)

    corpus = sub.add_parser("corpus", help="write the fleet corpus from skill checkouts")
    corpus.add_argument("directory", help="directory holding one checkout per skill")
    corpus.add_argument("--out", default="corpus", help="where to write <lang>.json (corpus/)")
    corpus.add_argument("--lang", action="append", help="only these languages (default: all)")
    corpus.set_defaults(func=cmd_corpus)

    model = sub.add_parser("model", help="train the intent classifier from the corpus")
    model.add_argument("corpus", help="directory of corpus files (<lang>.json)")
    model.add_argument("--out", default="model", help="model directory to write (model/)")
    model.add_argument("--base", default=None, help="base model2vec model (default: the kit's)")
    model.add_argument("--name", default="thalovant-m2v-intents")
    model.add_argument("--test-size", type=float, default=0.2, help="held-out share per label")
    model.add_argument("--max-epochs", type=int, default=-1, help="-1: until early stopping")
    model.set_defaults(func=cmd_model)

    args = parser.parse_args(argv)
    if args.command == "new" and not 91 <= args.priority <= 100:
        parser.error("--priority must be between 91 and 100")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
