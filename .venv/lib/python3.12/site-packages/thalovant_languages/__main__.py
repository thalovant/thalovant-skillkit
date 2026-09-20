"""``thalovant-languages check [DIR]``, ``list`` and ``show TAG``: the gate a
checkout runs before a language is released, and a way to see what a tag
resolves to."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import KEYS, __version__, check, described, language, root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="thalovant-languages",
                                     description="The words every Thalovant rule turns on, per language.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    checker = commands.add_parser("check", help="Refuse a data tree that a component could not read.")
    checker.add_argument("directory", nargs="?", help="a languages/ tree (default: the installed data)")
    commands.add_parser("list", help="Every described language.")
    shower = commands.add_parser("show", help="What a tag resolves to, and which keys it carries.")
    shower.add_argument("tag")
    args = parser.parse_args(argv)

    if args.command == "check":
        where = Path(args.directory) if args.directory else None
        problems = check(where)
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{where or root()}: {'sound' if not problems else f'{len(problems)} problem(s)'}")
        return 1 if problems else 0
    if args.command == "list":
        for tag in described():
            print(tag)
        return 0
    data = language(args.tag)
    if not data:
        print(f"{args.tag}: nothing describes this language", file=sys.stderr)
        return 1
    for key in KEYS:
        if key in data:
            value = data[key]
            size = len(value) if hasattr(value, "__len__") else 1
            print(f"{key}: {size}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
