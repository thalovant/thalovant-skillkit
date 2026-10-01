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
import string
from collections import Counter
from pathlib import Path

from .regions import regional_sources, sync_regions
from .ssml import looks_like_ssml, to_plain, validate
from .text import fold_words

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


#: The punctuation a language joins a list with. A swallowed list arrives
#: joined in the *target* language's marks, not English's, so the full-width
#: comma, the ideographic comma and the Arabic comma all have to count: a
#: Chinese "每天，每日" is as collapsed as a Spanish "cada día, todos los días".
LIST_PUNCTUATION = (",", "\uff0c", "\u3001", "\u060c")


def _repeated_run(alias: str) -> str | None:
    """The same words, or the same characters, twice in a row."""
    words = alias.lower().split()
    for size in range(1, len(words) // 2 + 1):
        for start in range(len(words) - 2 * size + 1):
            if words[start:start + size] == words[start + size:start + 2 * size]:
                return " ".join(words[start:start + size])
    # A language that does not write spaces collapses into one long run
    # instead, so look at the characters -- but only when there are no spaces
    # to go on, and only when the repeat is the WHOLE alias. Both halves of
    # that matter: Spanish "cada día" is c-a-d-a-d-í-a and carries "ad" twice,
    # and German "Wochenende" carries "en" twice, and both are ordinary words.
    # A swallowed list in such a language is the same unit over and over and
    # nothing else, as in a "weekly" that reads 週に週に週に週に.
    if not any(character.isspace() for character in alias):
        letters = alias.lower()
        for size in range(1, len(letters) // 2 + 1):
            if len(letters) % size:
                continue
            unit = letters[:size]
            if unit * (len(letters) // size) == letters:
                return unit
    return None


def collapsed_alias(alias: str) -> str | None:
    """Why this alias looks like a whole list that lost its separators.

    A ``.voc`` line is ``canonical|alias|alias|...``. Hand a translator the
    aliases as one unit and it answers with one string -- joined by a comma,
    by a space, or by nothing at all -- and the line then offers one long
    alias nobody would ever say in place of the several short ones people do.

    Two tells, both chosen for precision rather than reach. A comma: a
    vocabulary term is a thing somebody says, not a list. And the same words
    twice running: several English synonyms translate to the same phrase in
    most languages, so a swallowed list repeats itself where a real alias does
    not. Deliberately quiet about a locale that simply has fewer aliases than
    English -- no abbreviation for Monday, one word where English has three --
    because how many ways a language offers to say a thing is its own
    business, exactly as with the placeholder check above.
    """
    alias = alias.strip()
    if not alias:
        return None
    # Repeated digits are numbers, not duplicated translations (11, 88, ...).
    if alias.isdecimal():
        return None
    separator = next((mark for mark in LIST_PUNCTUATION if mark in alias), None)
    if separator is not None:
        return (f"contains {separator!r}, so it reads as a list rather than one term")
    repeated = _repeated_run(alias)
    if repeated:
        return f"repeats {repeated!r}, so it reads as several aliases run together"
    return None


def pipe_outside_group(line: str) -> bool:
    """Whether `line` has a `|` that no `(...)` or `[...]` encloses.

    OVOS-INTENT-1 §3.6 reads such a pipe as neither a branch nor literal text,
    and from ovos-spec-tools 1.14 expanding the line raises. ovos-workshop
    expands every `.voc` under a skill's locale tree when the skill registers
    an intent with a vocabulary blacklist, so one `key|alias` line in any
    `.voc` stops the whole skill loading. A table the skill parses itself
    belongs in `tables/<name>.table`, which OVOS never reads.
    """
    depth = 0
    for char in line:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(depth - 1, 0)
        elif char == "|" and depth == 0:
            return True
    return False


def vocab_problems(text: str) -> list[tuple[int, str, str]]:
    """Report collapsed lists, respecting explicitly documented literal aliases.

    Natural reduplication cannot be distinguished from a duplicated translation
    by spelling alone. A ``# skillkit: literal-alias <text>`` comment exempts
    that exact alias in this file; other aliases on the same line remain checked.
    """
    found: list[tuple[int, str, str]] = []
    prefix = "# skillkit: literal-alias "
    literals = {line.strip()[len(prefix):].strip().casefold()
                for line in text.splitlines() if line.strip().startswith(prefix)}
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "|" not in stripped:
            continue
        for alias in stripped.split("|")[1:]:
            if alias.strip().casefold() in literals:
                continue
            reason = collapsed_alias(alias)
            if reason:
                found.append((number, alias.strip(), reason))
    return found


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
    try:
        regional_bases = regional_sources(locale_root)
    except (OSError, ValueError, KeyError, TypeError):
        regional_bases = {}  # sync_regions reports the precise manifest error.
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
    # An SSML twin is optional in every locale: without one a language says
    # the plain line, as it always has. So it is not "missing" anywhere, and
    # its placeholders are held to its own plain twin by check_ssml rather
    # than to English -- its tags differ between languages by design.
    source_files = {path for path in _files_under(source_root) if path.suffix != SSML_SUFFIX}

    for locale in sorted(supported & present):
        target_root = locale_root / locale
        target_files = _files_under(target_root)
        for relative in sorted(source_files - target_files):
            problems.append(f"locale/{locale}/{relative} is missing ({SOURCE_LOCALE} has it)")
        for relative in sorted(source_files & target_files):
            source, target = source_root / relative, target_root / relative
            base = regional_bases.get(locale, locale)
            if base not in PLACEHOLDER_EXEMPT and locale != SOURCE_LOCALE:
                # Compared as sets, not counts. English offers two variant
                # lines for most replies and French follows; every other
                # translation in the fleet writes one careful line. Counting
                # occurrences flagged 162 files in one skill for exactly that,
                # and is why five skills never adopted this check at all. What
                # must never differ is the set: an invented placeholder raises
                # KeyError mid-reply, a missing one loses what the reply was
                # meant to say. How many variants a language offers is its
                # own business.
                want, got = set(_placeholders(source)), set(_placeholders(target))
                if want != got:
                    missing = sorted(want - got)
                    extra = sorted(got - want)
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
            elif relative.suffix in {".voc", ".table"}:
                text = target.read_text(encoding="utf-8")
                for number, alias, reason in vocab_problems(text):
                    problems.append(f"locale/{locale}/{relative}:{number} "
                                    f"alias {alias!r} {reason}")
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

    # Every .voc OVOS will read, not only those en-US also ships: workshop
    # walks the whole locale tree, so a file one language alone carries
    # stops the skill loading just the same.
    for voc in sorted(locale_root.rglob("*.voc")):
        where = voc.relative_to(locale_root).as_posix()
        for number, line in enumerate(voc.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or not pipe_outside_group(stripped):
                continue
            problems.append(
                f"locale/{where}:{number} has a | outside a group, which OVOS refuses "
                f"to load; write (a|b), or move a key|alias table to tables/{voc.stem}.table")
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
        try:
            import tomllib  # 3.11+
        except ImportError:  # pragma: no cover - 3.10 gets the same parser from PyPI
            import tomli as tomllib

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


SSML_SUFFIX = ".ssml"
_FORMAT = string.Formatter()
_MUSTACHE = re.compile(r"\{\{+\s*(.*?)\s*\}\}+")
# `(a|b)` and `[optional]`: OVOS picks one expansion at random, and the same
# choice cannot be made in the SSML line, so the pair could say different words.
_ALTERNATIVES = re.compile(r"\([^()]*\|[^()]*\)|\[[^\[\]]*\]")


def _resource_lines(path: Path) -> list[tuple[int, str]]:
    """(line number, text) for each line a dialog renders: no blanks, no comments."""
    return [(number, line.strip())
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if line.strip() and not line.strip().startswith("#")]


def _fields(template: str) -> set[str] | None:
    """The `{placeholders}` a line fills, or None when its braces do not parse."""
    template = _MUSTACHE.sub(r"{\1}", template)
    try:
        return {name.split(".")[0].split("[")[0]
                for _, name, _, _ in _FORMAT.parse(template) if name is not None}
    except ValueError:
        return None


def _ssml_line_problems(where: str, plain: str, ssml: str) -> list[str]:
    problems = [f"{where}: {problem}" for problem in validate(ssml)]
    if problems:
        return problems
    want, got = _fields(plain), _fields(ssml)
    if got is None:
        return [f"{where}: its braces do not parse as {{placeholders}}"]
    if want is not None and want != got:
        detail = []
        if want - got:
            detail.append(f"missing {sorted(want - got)}")
        if got - want:
            detail.append(f"unexpected {sorted(got - want)}")
        problems.append(f"{where}: placeholders differ from the plain line "
                        f"({'; '.join(detail)})")
    if _ALTERNATIVES.search(plain) or _ALTERNATIVES.search(ssml):
        problems.append(f"{where}: (a|b) and [optional] cannot be paired with markup; "
                        "write each variant on its own line in both files")
    if problems:
        return problems  # the words cannot match either; one reason is enough
    said = fold_words(plain)
    if said not in (fold_words(to_plain(ssml)), fold_words(to_plain(ssml, alias=False))):
        problems.append(f"{where}: does not say the same words as the plain line "
                        f"({to_plain(ssml, alias=False)!r} against {plain!r})")
    return problems


def check_ssml(skill_root: Path) -> list[str]:
    """Every `.ssml` twin can be sent beside its dialog, and no dialog holds markup.

    A twin sits beside its plain dialog -- `dialog/joke.ssml` beside
    `dialog/joke.dialog` -- with as many lines, and line N is line N: well-formed,
    only the tags Thalovant voices render, the same `{placeholders}`, and the
    same words once the markup is read out. A plain `.dialog` holds no SSML
    tags at all: it is what the Android app shows and says as written, and
    OVOS's renderer raises on a `<break/>` in one. Every locale directory is
    read, whether or not supported.json lists it.
    """
    package = find_package(Path(skill_root))
    if package is None or not (package / "locale").is_dir():
        return []
    locale_root = package / "locale"
    problems: list[str] = []
    for path in sorted(locale_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(locale_root)
        if path.suffix == ".dialog":
            for number, line in _resource_lines(path):
                if looks_like_ssml(line):
                    hint = (f"; name the twin {path.name[:-len('.ssml.dialog')]}.ssml, since "
                            "OVOS reads every .dialog as a plain template"
                            if path.name.endswith(".ssml.dialog")
                            else f"; put the markup in {path.stem}.ssml beside it")
                    problems.append(f"locale/{relative}:{number} holds SSML markup, which "
                                    f"clients without SSML say and show as written{hint}")
        elif path.suffix == SSML_SUFFIX:
            plain_path = path.with_suffix(".dialog")
            if not plain_path.is_file():
                problems.append(f"locale/{relative} has no {plain_path.name} beside it; "
                                "a twin is only sent with its plain dialog")
                continue
            plain, twins = _resource_lines(plain_path), _resource_lines(path)
            if len(plain) != len(twins):
                problems.append(f"locale/{relative} has {len(twins)} line(s) and "
                                f"{plain_path.name} has {len(plain)}; line N is sent with "
                                "line N, so both need one line per variant")
                continue
            for (_, plain_line), (number, ssml_line) in zip(plain, twins, strict=True):
                problems.extend(_ssml_line_problems(f"locale/{relative}:{number}",
                                                    plain_line, ssml_line))
    return problems


def check_all(skill_root: Path) -> list[str]:
    """Every check, in the order a person would want to read them."""
    root = Path(skill_root)
    package = find_package(root)
    return (
        check_entry_point(root)
        + check_package_data(root)
        + check_fallback_priority(root)
        + check_locale_contract(root)
        + check_ssml(root)
        + (sync_regions(package / "locale") if package else [])
    )
