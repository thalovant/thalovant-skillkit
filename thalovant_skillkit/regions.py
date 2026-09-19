"""Build complete OVOS locale trees from shared translations and regional edits.

This is an authoring tool, not a translator or a runtime resource loader. All
wording lives in the skill's locale/regional.json. Generated files ship normally
in the wheel, so native OVOS and code that opens files directly see the same text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

TAG = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})+")
SLOT = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}|<[A-Za-z_][A-Za-z0-9_.-]*>")


def _files(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"{root.name}: expected a real locale directory")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"{path}: locale symlinks are not supported")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return result


def regional_sources(locale_root: Path) -> dict[str, str]:
    """Read and validate regional definitions before touching generated files."""
    if locale_root.is_symlink():
        raise ValueError("locale directory must not be a symlink")
    manifest = locale_root / "regional.json"
    if manifest.is_symlink():
        raise ValueError("regional.json must not be a symlink")
    if not manifest.exists():
        return {}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("regional.json: expected version 1")
    regions = data.get("locales")
    if not isinstance(regions, dict):
        raise ValueError("regional.json: locales must be an object")
    sources = {}
    for target, definition in regions.items():
        if not TAG.fullmatch(target) or not isinstance(definition, dict):
            raise ValueError(f"regional.json: invalid target {target!r}")
        source = definition.get("source")
        if not isinstance(source, str) or not TAG.fullmatch(source):
            raise ValueError(f"regional.json: invalid source for {target}")
        if source in regions or source.split("-")[0] != target.split("-")[0]:
            raise ValueError(f"regional.json: {target} needs a base in the same language; "
                             "no chains")
        overrides = definition.get("overrides", {})
        if not isinstance(overrides, dict):
            raise ValueError(f"regional.json: {target} overrides must be an object")
        for name, text in overrides.items():
            path = PurePosixPath(name)
            if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
                    or str(path) != name or not isinstance(text, str)):
                raise ValueError(f"regional.json: invalid override {target}/{name}")
        sources[target] = source
    return sources


def regional_plan(locale_root: Path) -> dict[str, dict[str, str]]:
    """Resolve every region in memory, failing before any write on invalid input."""
    sources = regional_sources(locale_root)
    if not sources:
        return {}
    data = json.loads((locale_root / "regional.json").read_text(encoding="utf-8"))
    plan = {}
    for target, source in sources.items():
        shared = _files(locale_root / source)
        overrides = data["locales"][target].get("overrides", {})
        for name in overrides:
            if name not in shared:
                raise ValueError(f"regional.json: {target}/{name} has no source file in {source}")
            if set(SLOT.findall(shared[name])) != set(SLOT.findall(overrides[name])):
                raise ValueError(f"regional.json: {target}/{name} changes source placeholders")
        plan[target] = shared | overrides
        destination = locale_root / target
        if destination.exists() or destination.is_symlink():
            existing = _files(destination)
            extras = existing.keys() - plan[target].keys()
            if extras:
                raise ValueError(f"{target}: remove obsolete generated files explicitly: "
                                 + ", ".join(sorted(extras)))
    return plan


def sync_regions(locale_root: Path, *, write: bool = False) -> list[str]:
    """Check freshness, or regenerate managed regions and declare their support.

No network access or language guessing. Existing source locales are never
changed. Unexpected files are reported rather than silently deleted.
"""
    locale_root = Path(locale_root)
    try:
        plan = regional_plan(locale_root)
        if not plan:
            return []
        supported_file = locale_root / "supported.json"
        if supported_file.is_symlink():
            raise ValueError("supported.json must not be a symlink")
        supported = json.loads(supported_file.read_text(encoding="utf-8"))
        declared = supported["locales"]
        if not isinstance(declared, list) or not all(isinstance(tag, str) for tag in declared):
            raise ValueError("supported.json: locales must be a list of strings")
        problems = []
        for target, files in plan.items():
            for name, text in files.items():
                path = locale_root / target / name
                if not path.is_file() or path.read_text(encoding="utf-8") != text:
                    if write:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(text, encoding="utf-8")
                    else:
                        problems.append(f"locale/{target}/{name}: regenerate with "
                                        "thalovant-skillkit locales --write")
            if target not in declared:
                problems.append(f"locale/{target}: missing from supported.json")
        if write:
            supported["locales"] = sorted(set(declared) | plan.keys())
            supported_file.write_text(json.dumps(supported, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
            return []
        return problems
    except (OSError, ValueError, KeyError, TypeError) as failure:
        return [f"regional locales: {failure}"]
