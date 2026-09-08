"""What every skill's CI should check, kept in one place.

The locale contract below was a 59-line test file vendored byte-for-byte into
fifteen skills. Changing a rule meant fifteen pull requests, and a skill that
missed the copy shipped a translation with a missing placeholder that nobody
caught until it was heard. The other checks catch the packaging mistakes that
read as a broken skill: an entry point naming a class that does not exist, or
a `locale/` tree left out of the wheel so every reply is a dialog file's name.

Each check returns a list of problems, empty when all is well, so the same
functions serve a test (`assert not problems`) and the command line.

    # test/test_contract.py -- the whole file
    from pathlib import Path
    from thalovant_skillkit.checks import check_all

    def test_the_skill_keeps_its_contracts():
        assert check_all(Path(__file__).parents[1]) == []
"""
from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path

PLACEHOLDER = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}|<[A-Za-z_][A-Za-z0-9_.-]*>")
# skill.json keys that describe the package rather than the language, and so
# must not differ between locales.
TECHNICAL_SKILL_KEYS = frozenset({
    "author", "icon", "images", "license", "package_name",
    "pip_spec", "skill_id", "source", "tags", "version",
})
SOURCE_LOCALE = "en-US"
# Locales whose translators may legitimately reorder or drop a placeholder.
# French was exempt in every vendored copy of this check; kept so adopting the
# shared version changes nothing.
PLACEHOLDER_EXEMPT = frozenset({"fr-FR"})
LOW_BAND = range(91, 101)


def find_package(skill_root: Path) -> Path | None:
    """The `thalovant_skill_*` package directory, or None."""
    for candidate in sorted(Path(skill_root).glob("thalovant_skill_*")):
        if (candidate / "__init__.py").is_file():
            return candidate
    return None


def _files_under(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


def _placeholders(path: Path) -> Counter[str]:
    return Counter(PLACEHOLDER.findall(path.read_text(encoding="utf-8")))


def check_locale_contract(skill_root: Path) -> list[str]:
    """Every supported locale carries every en-US resource, with the same
    placeholders, valid JSON, compiling regexes, and matching package metadata.
    """
    skill_root = Path(skill_root)
    package = find_package(skill_root)
    if package is None:
        return [f"no thalovant_skill_* package under {skill_root}"]
    locale_root = package / "locale"
    if not locale_root.is_dir():
        return [f"{package.name} has no locale/ directory"]

    problems: list[str] = []
    supported_file = locale_root / "supported.json"
    if not supported_file.is_file():
        return ["locale/supported.json is missing; it lists the locales this skill ships"]
    try:
        supported = set(json.loads(supported_file.read_text(encoding="utf-8"))["locales"])
    except (ValueError, KeyError, TypeError) as failure:
        return [f'locale/supported.json must be {{"locales": [...]}}: {failure}']

    present = {p.name for p in locale_root.iterdir() if p.is_dir()}
    for locale in sorted(supported - present):
        problems.append(f"locale/{locale} is listed in supported.json but has no directory")

    source_root = locale_root / SOURCE_LOCALE
    if not source_root.is_dir():
        return problems + [
            f"locale/{SOURCE_LOCALE} is missing; every other locale is checked against it"
        ]
    source_files = _files_under(source_root)

    for locale in sorted(supported & present):
        target_root = locale_root / locale
        target_files = _files_under(target_root)
        for relative in sorted(source_files - target_files):
            problems.append(f"locale/{locale}/{relative} is missing ({SOURCE_LOCALE} has it)")
        for relative in sorted(source_files & target_files):
            source, target = source_root / relative, target_root / relative
            if locale not in PLACEHOLDER_EXEMPT and locale != SOURCE_LOCALE:
                want, got = _placeholders(source), _placeholders(target)
                if relative.suffix == ".intent":
                    # Several English phrasings can translate to one, so a
                    # translated intent file may repeat a slot fewer times.
                    # It must still carry every slot and invent none. One
                    # skill's copy of this check had learned that; the other
                    # fifteen had not.
                    want, got = Counter(set(want)), Counter(set(got))
                if want != got:
                    missing = sorted((want - got).elements())
                    extra = sorted((got - want).elements())
                    detail = []
                    if missing:
                        detail.append(f"missing {missing}")
                    if extra:
                        detail.append(f"unexpected {extra}")
                    problems.append(f"locale/{locale}/{relative}: placeholders differ from "
                                    f"{SOURCE_LOCALE} ({'; '.join(detail)})")
            if relative.suffix == ".json":
                try:
                    json.loads(target.read_text(encoding="utf-8"))
                except ValueError as failure:
                    problems.append(f"locale/{locale}/{relative} is not valid JSON: {failure}")
            elif relative.suffix == ".rx":
                lines = target.read_text(encoding="utf-8").splitlines()
                for number, pattern in enumerate(lines, 1):
                    if pattern.strip() and not pattern.lstrip().startswith("#"):
                        try:
                            re.compile(pattern)
                        except re.error as failure:
                            problems.append(f"locale/{locale}/{relative}:{number} "
                                            f"does not compile: {failure}")

        metadata = source_root / "skill.json"
        if metadata.is_file() and (target_root / "skill.json").is_file():
            try:
                source_data = json.loads(metadata.read_text(encoding="utf-8"))
                target_data = json.loads((target_root / "skill.json").read_text(encoding="utf-8"))
            except ValueError:
                continue  # reported above
            for key in sorted(TECHNICAL_SKILL_KEYS & source_data.keys() & target_data.keys()):
                if target_data[key] != source_data[key]:
                    problems.append(f"locale/{locale}/skill.json: {key} differs from "
                                    f"{SOURCE_LOCALE} but is not a translatable field")
    return problems


def check_fallback_priority(skill_root: Path) -> list[str]:
    """A FALLBACK_PRIORITY, wherever it is declared, sits in the low band.

    Looks at the module and at every class body, and follows a class attribute
    that names a module constant -- the fleet's older skills declare the number
    once at module level and repeat it on the class.
    """
    package = find_package(Path(skill_root))
    if package is None:
        return []
    source = (package / "__init__.py").read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as failure:
        return [f"{package.name}/__init__.py does not parse: {failure}"]

    def assignments(body):
        for node in body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "FALLBACK_PRIORITY":
                        yield node.value

    module_level = {ast.unparse(v): v for v in assignments(tree.body)}
    declared = list(module_level.values())
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for value in assignments(node.body):
                # `FALLBACK_PRIORITY = FALLBACK_PRIORITY` on the class points at
                # the module constant, already collected above.
                if isinstance(value, ast.Name) and value.id == "FALLBACK_PRIORITY":
                    continue
                declared.append(value)

    problems: list[str] = []
    for value in declared:
        number = getattr(value, "value", None)
        if isinstance(number, bool) or not isinstance(number, int):
            continue  # computed at runtime; the skill's own test covers it
        if number not in LOW_BAND:
            problems.append(
                f"FALLBACK_PRIORITY = {number} is outside 91-100; "
                f"below 91 it outranks every skill with a narrower job"
            )
    return problems


SKILL_ENTRY_GROUPS = ("opm.skill", "ovos.plugin.skill")


def _entry_points(skill_root: Path) -> list[str]:
    """Skill entry-point specs from setup.py or pyproject.toml.

    Only the skill groups: a skill may also register metrics or other hooks,
    and those name functions, not skill classes.
    """
    found: list[str] = []
    setup = skill_root / "setup.py"
    if setup.is_file():
        text = setup.read_text(encoding="utf-8")
        # The fleet builds the spec from constants; resolve that shape.
        parts = dict(re.findall(r'^(\w+)\s*=\s*["\']([^"\']+)["\']', text, re.M))
        if {"SKILL_NAME", "SKILL_AUTHOR", "SKILL_PKG", "SKILL_CLAZZ"} <= parts.keys():
            found.append(f"{parts['SKILL_NAME']}.{parts['SKILL_AUTHOR']}="
                         f"{parts['SKILL_PKG']}:{parts['SKILL_CLAZZ']}")
        for group in SKILL_ENTRY_GROUPS:
            found += re.findall(
                rf'["\']{re.escape(group)}["\']\s*:\s*\[?\s*["\']([^"\']+=[^"\']+)["\']', text)
    pyproject = skill_root / "pyproject.toml"
    if pyproject.is_file():
        import tomllib

        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            data = {}
        groups = data.get("project", {}).get("entry-points", {})
        for group in SKILL_ENTRY_GROUPS:
            for name, target in (groups.get(group) or {}).items():
                found.append(f"{name}={target}")
    return list(dict.fromkeys(found))


def check_entry_point(skill_root: Path) -> list[str]:
    """The declared entry point names a class that exists in the package."""
    skill_root = Path(skill_root)
    package = find_package(skill_root)
    if package is None:
        return []
    specs = _entry_points(skill_root)
    if not specs:
        return ["no skill entry point declared; the hub cannot find a skill without one"]
    try:
        tree = ast.parse((package / "__init__.py").read_text(encoding="utf-8"))
    except SyntaxError:
        return []  # reported by check_fallback_priority
    classes = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    exported = {a.asname or a.name for n in tree.body if isinstance(n, ast.ImportFrom)
                for a in n.names}
    problems: list[str] = []
    for spec in specs:
        target = spec.split("=", 1)[-1].strip()
        module, _, clazz = target.partition(":")
        if module.split(".")[0] != package.name:
            problems.append(f"entry point {spec!r} names module {module!r}, "
                            f"but the package is {package.name!r}")
        elif clazz not in classes | exported:
            problems.append(f"entry point {spec!r} names class {clazz!r}, "
                            f"which {package.name}/__init__.py does not define")
    return problems


def check_package_data(skill_root: Path) -> list[str]:
    """The locale tree is going to be in the wheel.

    Left out, the installed skill has no dialog files and answers with their
    names -- which reads as a broken skill rather than a packaging mistake.
    """
    skill_root = Path(skill_root)
    package = find_package(skill_root)
    if package is None or not (package / "locale").is_dir():
        return []
    declared = ""
    for name in ("setup.py", "pyproject.toml", "MANIFEST.in"):
        path = skill_root / name
        if path.is_file():
            declared += path.read_text(encoding="utf-8")
    if "locale" in declared or "find_resource_files" in declared:
        return []
    return ["locale/ is not named in package_data, MANIFEST.in or pyproject; "
            "the installed skill will have no dialog or vocabulary files"]


def check_all(skill_root: Path) -> list[str]:
    """Every check, in the order a person would want to read them."""
    root = Path(skill_root)
    return (
        check_entry_point(root)
        + check_package_data(root)
        + check_fallback_priority(root)
        + check_locale_contract(root)
    )
