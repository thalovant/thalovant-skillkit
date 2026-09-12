"""Check built distributions against the files their source tree promises.

This module reads archives without extracting them or importing a skill. All
checks use the standard library and return problem strings, like ``checks``.
Installed-plugin discovery belongs in a separate clean environment: importing
from the checkout cannot prove that the installed wheel works.
"""
from __future__ import annotations

import hashlib
import lzma
import re
import stat
import tarfile
import zipfile
import zlib
from collections.abc import Callable, Iterable, Mapping
from email import policy
from email.parser import BytesParser
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import BinaryIO

_CACHES = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
_ARCHIVE_ERRORS = (
    OSError, ValueError, RuntimeError, EOFError, NotImplementedError,
    zipfile.BadZipFile, tarfile.TarError, zlib.error, lzma.LZMAError,
)


def _member_name(name: str) -> str:
    """Normalize harmless ./ prefixes, while refusing nonportable unsafe paths."""
    path = PurePosixPath(name)
    if (not name or "\0" in name or "\\" in name or path.is_absolute()
            or ".." in path.parts or not path.parts or re.match(r"^[A-Za-z]:", str(path))):
        raise ValueError(f"unsafe archive path {name!r}")
    return str(path)


def _digest(stream: BinaryIO) -> bytes:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(64 * 1024), b""):
        digest.update(chunk)
    return digest.digest()


def _source_files(root: Path, paths: Iterable[str | Path], *, packages: bool = False
                  ) -> tuple[dict[str, Path], list[str]]:
    expected: dict[str, Path] = {}
    problems: list[str] = []
    for raw in paths:
        source = root / raw
        try:
            relative = source.relative_to(root)
            source.resolve().relative_to(root)
        except ValueError:
            problems.append(f"source path must stay inside {root}: {raw}")
            continue
        if ".." in relative.parts:
            problems.append(f"source path contains traversal: {raw}")
            continue
        if not source.exists():
            problems.append(f"declared source path is missing: {raw}")
            continue
        if packages and not source.is_dir():
            problems.append(f"package directory is not a directory: {raw}")
            continue
        files = [source, *sorted(source.rglob("*"))] if source.is_dir() else [source]
        for file in files:
            if any(part in _CACHES for part in file.relative_to(root).parts):
                continue
            if file.is_symlink():
                problems.append(f"declared source path is a symlink: {file.relative_to(root)}")
                continue
            if not file.is_file() or file.suffix in {".pyc", ".pyo"}:
                continue
            archive_path = (Path(source.name) / file.relative_to(source) if packages
                            else file.relative_to(root)).as_posix()
            if archive_path in expected and expected[archive_path] != file:
                problems.append(f"multiple source files map to {archive_path}")
            expected[archive_path] = file
    return expected, problems


def _metadata(read: Callable[[str], BinaryIO], name: str) -> tuple[str, str]:
    with read(name) as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError(f"{name}: metadata exceeds 1 MiB")
    metadata = BytesParser(policy=policy.default).parsebytes(raw)
    if metadata.defects:
        raise ValueError(f"{name}: malformed metadata headers")
    for field in ("Metadata-Version", "Name", "Version"):
        values = metadata.get_all(field, [])
        if len(values) != 1 or not str(values[0]).strip():
            raise ValueError(f"{name}: expected one nonempty {field} header")
    return re.sub(r"[-_.]+", "-", str(metadata["Name"]).lower()), str(metadata["Version"])


def _check_contents(files: set[str], read: Callable[[str], BinaryIO],
                    expected: Mapping[str, Path], excludes: Iterable[str],
                    counts: Mapping[str, int]) -> list[str]:
    problems = []
    for name, source in sorted(expected.items()):
        if name not in files:
            problems.append(f"missing resource: {name}")
            continue
        try:
            with source.open("rb") as original, read(name) as bundled:
                if _digest(original) != _digest(bundled):
                    problems.append(f"resource bytes differ from source: {name}")
        except _ARCHIVE_ERRORS as failure:
            problems.append(f"cannot read resource {name}: {failure}")
    for pattern in excludes:
        for name in sorted(files):
            if (name == pattern.rstrip("/") or name.startswith(pattern.rstrip("/") + "/")
                    or fnmatchcase(name, pattern)):
                problems.append(f"forbidden resource: {name} (matches {pattern!r})")
    for pattern, wanted in counts.items():
        actual = sum(fnmatchcase(name, pattern) for name in files)
        if actual != wanted:
            problems.append(f"resource count for {pattern!r}: expected {wanted}, found {actual}")
    return problems


def _check_archive(path: Path, kind: str, expected: Mapping[str, Path],
                   excludes: Iterable[str], counts: Mapping[str, int]
                   ) -> tuple[list[str], tuple[str, str] | None]:
    problems: list[str] = []
    identity = None
    try:
        archive = zipfile.ZipFile(path) if kind == "wheel" else tarfile.open(path, "r:*")
        with archive:
            entries = archive.infolist() if kind == "wheel" else archive.getmembers()
            files, seen = {}, set()
            for entry in entries:
                raw = entry.filename if kind == "wheel" else entry.name
                try:
                    name = _member_name(raw)
                except ValueError as failure:
                    problems.append(str(failure))
                    continue
                if name in seen:
                    problems.append(f"duplicate archive member: {name}")
                seen.add(name)
                if kind == "wheel":
                    mode = stat.S_IFMT(entry.external_attr >> 16)
                    is_directory = entry.is_dir()
                    regular = mode in {0, stat.S_IFREG} and not is_directory
                    special = (mode not in {0, stat.S_IFREG, stat.S_IFDIR}
                               or (mode == stat.S_IFDIR and not is_directory))
                else:
                    is_directory, regular = entry.isdir(), entry.isfile()
                    special = not (is_directory or regular)
                if special:
                    problems.append(f"unsupported archive member type: {name}")
                elif regular:
                    files[name] = entry

            if kind == "sdist":
                prefixes = {PurePosixPath(name).parts[0] for name in seen}
                if len(prefixes) != 1:
                    raise ValueError("sdist must contain exactly one top-level directory")
                prefix = prefixes.pop() + "/"
                if any(not name.startswith(prefix) for name in files):
                    raise ValueError("sdist contains a file outside its top-level directory")
                files = {name[len(prefix):]: entry for name, entry in files.items()}

            def read(name):
                if kind == "wheel":
                    return archive.open(files[name])
                stream = archive.extractfile(files[name])
                if stream is None:
                    raise OSError(f"not a regular archive file: {name}")
                return stream

            problems.extend(_check_contents(set(files), read, expected, excludes, counts))
            if kind == "wheel":
                metadata_dirs = {name.split("/", 1)[0] for name in files
                                 if name.split("/", 1)[0].endswith(".dist-info")}
                if len(metadata_dirs) != 1:
                    raise ValueError("wheel must contain exactly one .dist-info directory")
                metadata_dir = metadata_dirs.pop()
                for required in ("WHEEL", "METADATA", "RECORD"):
                    if f"{metadata_dir}/{required}" not in files:
                        raise ValueError(f"wheel is missing {metadata_dir}/{required}")
                with read(f"{metadata_dir}/WHEEL") as stream:
                    raw_headers = stream.read(1024 * 1024)
                    headers = BytesParser(policy=policy.default).parsebytes(raw_headers)
                if headers.defects or not headers.get("Wheel-Version"):
                    raise ValueError("wheel has malformed WHEEL metadata")
                identity = _metadata(read, f"{metadata_dir}/METADATA")
            else:
                if "PKG-INFO" not in files:
                    raise ValueError("sdist is missing PKG-INFO")
                identity = _metadata(read, "PKG-INFO")
    except _ARCHIVE_ERRORS as failure:
        problems.append(f"cannot validate {kind}: {failure}")
    return [f"{path.name}: {problem}" for problem in problems], identity


def check_artifacts(
    source_root: str | Path,
    *,
    wheel: str | Path | None = None,
    sdist: str | Path | None = None,
    package_dirs: Iterable[str | Path] | None = None,
    runtime_paths: Iterable[str | Path] = (),
    source_paths: Iterable[str | Path] = (),
    wheel_excludes: Iterable[str] = (),
    wheel_counts: Mapping[str, int] | None = None,
    sdist_counts: Mapping[str, int] | None = None,
) -> list[str]:
    """Validate built resources, archive structure, metadata, and source bytes.

    ``package_dirs`` names top-level import-package directories, including
    ``src/package`` layouts. Every file beneath them is required in both
    artifacts, except interpreter/tool caches. Wheel paths start with the
    package directory's name; sdist paths retain the source directory layout.
    When omitted, the first ``thalovant_skill_*`` package is discovered.

    ``runtime_paths`` are additional source-root-relative files/directories
    required at the same relative path in both artifacts. ``source_paths``
    are required only in the sdist (for example offline regeneration inputs).
    ``wheel_excludes`` accepts paths, directory prefixes, or shell-style globs;
    the count mappings constrain complete archive inventories by glob.

    At least one archive is required. Nothing is extracted, installed, imported,
    or fetched. Run installed-plugin smoke tests separately, outside the source
    checkout, after installing the wheel in a clean environment.
    """
    if wheel is None and sdist is None:
        return ["provide at least one wheel or sdist to validate"]
    root = Path(source_root).resolve()
    if package_dirs is None:
        from .checks import find_package

        package = find_package(root)
        if package is None:
            return [f"no thalovant_skill_* package under {root}; provide package_dirs"]
        package_dirs = [package]
    package_dirs = list(package_dirs)
    runtime_paths = list(runtime_paths)
    try:
        runtime, problems = _source_files(root, package_dirs, packages=True)
        additions, extra_problems = _source_files(root, runtime_paths)
        problems.extend(extra_problems)
        for name, source in additions.items():
            if name in runtime and runtime[name] != source:
                problems.append(f"multiple source files map to {name}")
            runtime[name] = source
        sources, extra_problems = _source_files(
            root, [*package_dirs, *runtime_paths, *(source_paths if sdist is not None else ())],
        )
        problems.extend(extra_problems)
    except OSError as failure:
        return [f"cannot read declared source resources: {failure}"]
    if problems:
        return list(dict.fromkeys(problems))
    if not runtime and not sources:
        return ["no declared source resources to validate"]
    identities = []
    for artifact, kind, expected, excluded, counts in (
        (wheel, "wheel", runtime, wheel_excludes, wheel_counts or {}),
        (sdist, "sdist", sources, (), sdist_counts or {}),
    ):
        if artifact is not None:
            failures, identity = _check_archive(Path(artifact), kind, expected, excluded, counts)
            problems.extend(failures)
            if identity:
                identities.append(identity)
    if len(identities) == 2 and identities[0] != identities[1]:
        problems.append(f"wheel and sdist metadata disagree: {identities[0]} != {identities[1]}")
    return problems
