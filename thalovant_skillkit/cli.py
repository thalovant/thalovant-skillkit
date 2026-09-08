"""`thalovant-skillkit new` and `thalovant-skillkit check`.

Starting a skill used to mean copying an existing one and deleting what did not
apply, which carried its plumbing along -- and its mistakes. `new` writes a
complete skill that passes its own tests, with the conventions the fleet's CI
expects already in place. `check` runs those same checks on any skill.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .checks import check_all
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
test = ["pytest"]

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
    if not problems:
        print(f"ok: {root.name} keeps its contracts")
        return 0
    print(f"{len(problems)} problem(s) in {root.name}:")
    for problem in problems:
        print(f"  - {problem}")
    return 1


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
    check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    if args.command == "new" and not 91 <= args.priority <= 100:
        parser.error("--priority must be between 91 and 100")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
