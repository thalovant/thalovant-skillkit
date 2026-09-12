"""Built distributions must contain the actual resources, not just declarations."""
from __future__ import annotations

import io
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from thalovant_skillkit.artifacts import check_artifacts

PACKAGE = "thalovant_skill_example"
DIST_INFO = "example-1.0.dist-info"
METADATA = b"Metadata-Version: 2.1\nName: example\nVersion: 1.0\n\n"


def source_tree(root: Path, *, src_layout: bool = False) -> tuple[Path, dict[str, bytes]]:
    package = Path("src") / PACKAGE if src_layout else Path(PACKAGE)
    files = {
        (package / "__init__.py").as_posix(): b"class ExampleSkill:\n    pass\n",
        (package / "locale/en-US/hello.intent").as_posix(): b"hello\nhi there\n",
        (package / "locale/fr-FR/dialog/hello.dialog").as_posix(): "Salut à toi !\n".encode(),
        (package / "sounds/toot.ogg").as_posix(): b"OggS\x00\x01\x02recorded audio",
        "scripts/regenerate.py": b"print('rebuild')\n",
        "scripts/sources/recording.mp3": b"ID3original recording",
    }
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return package, files


def write_wheel(path: Path, files: dict[str, bytes], *, metadata: bool = True) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        if metadata:
            archive.writestr(f"{DIST_INFO}/METADATA", METADATA)
            archive.writestr(f"{DIST_INFO}/WHEEL",
                             b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
            archive.writestr(f"{DIST_INFO}/RECORD", b"")
    return path


def write_sdist(path: Path, files: dict[str, bytes], *, metadata: bytes | None = METADATA
                 ) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        contents = dict(files)
        if metadata is not None:
            contents["PKG-INFO"] = metadata
        for name, data in contents.items():
            info = tarfile.TarInfo("example-1.0/" + name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def package_files(files: dict[str, bytes], package: Path) -> dict[str, bytes]:
    prefix = package.as_posix() + "/"
    return {PACKAGE + "/" + name.removeprefix(prefix): data
            for name, data in files.items() if name.startswith(prefix)}


def test_complete_archives_match_resource_bytes_and_keep_sources_out_of_wheel(tmp_path):
    package, files = source_tree(tmp_path)
    wheel = write_wheel(tmp_path / "example.whl", package_files(files, package))
    sdist = write_sdist(tmp_path / "example.tar.gz", files)
    assert check_artifacts(
        tmp_path, wheel=wheel, sdist=sdist, source_paths=["scripts"],
        wheel_excludes=["scripts/sources", "*.mp3"],
        wheel_counts={"*.ogg": 1}, sdist_counts={"*.mp3": 1},
    ) == []


def test_src_layout_maps_package_in_wheel_but_preserves_source_layout_in_sdist(tmp_path):
    package, files = source_tree(tmp_path, src_layout=True)
    wheel = write_wheel(tmp_path / "example.whl", package_files(files, package))
    sdist = write_sdist(tmp_path / "example.tar.gz", files)
    assert check_artifacts(tmp_path, wheel=wheel, sdist=sdist, package_dirs=[package]) == []


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_missing_or_changed_localized_audio_resources_fail(tmp_path, kind, damage):
    package, files = source_tree(tmp_path)
    selected = package_files(files, package) if kind == "wheel" else dict(files)
    names = [f"{PACKAGE}/locale/fr-FR/dialog/hello.dialog", f"{PACKAGE}/sounds/toot.ogg"]
    for name in names:
        if damage == "missing":
            del selected[name]
        else:
            selected[name] = b"wrong bundled bytes"
    archive = (write_wheel(tmp_path / "example.whl", selected) if kind == "wheel"
               else write_sdist(tmp_path / "example.tar.gz", selected))
    problems = check_artifacts(tmp_path, **{kind: archive})
    assert len(problems) == 2
    assert all(any(name in problem for problem in problems) for name in names)
    assert all(("missing resource" if damage == "missing" else "bytes differ") in problem
               for problem in problems)


def test_additional_runtime_files_are_required_in_both_archives(tmp_path):
    package, files = source_tree(tmp_path)
    (tmp_path / "settings.json").write_text("{}")
    wheel = write_wheel(tmp_path / "example.whl", package_files(files, package))
    sdist = write_sdist(tmp_path / "example.tar.gz", files)
    problems = check_artifacts(tmp_path, wheel=wheel, sdist=sdist,
                               runtime_paths=["settings.json"])
    assert len(problems) == 2
    assert all("missing resource: settings.json" in problem for problem in problems)


def test_missing_source_only_resources_fail_sdist_but_do_not_affect_wheel(tmp_path):
    package, files = source_tree(tmp_path)
    wheel = write_wheel(tmp_path / "example.whl", package_files(files, package))
    sdist = write_sdist(tmp_path / "example.tar.gz", package_files(files, package))
    assert check_artifacts(tmp_path, wheel=wheel, source_paths=["not-present"]) == []
    problems = check_artifacts(tmp_path, wheel=wheel, sdist=sdist, source_paths=["scripts"])
    assert len(problems) == 2
    assert all("example.tar.gz: missing resource: scripts/" in problem for problem in problems)


def test_inventory_limits_and_exclusions_catch_unexpected_archive_files(tmp_path):
    package, files = source_tree(tmp_path)
    bundled = package_files(files, package)
    bundled["scripts/sources/private.mp3"] = b"unexpected source"
    bundled[f"{PACKAGE}/sounds/extra.ogg"] = b"unexpected sound"
    wheel = write_wheel(tmp_path / "example.whl", bundled)
    problems = check_artifacts(tmp_path, wheel=wheel, wheel_excludes=["scripts/sources"],
                               wheel_counts={"*.ogg": 1})
    assert any("forbidden resource: scripts/sources/private.mp3" in p for p in problems)
    assert any("expected 1, found 2" in p for p in problems)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/windows", "x\\..\\escape"])
@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_unsafe_member_paths_are_rejected_without_extraction(tmp_path, name, kind):
    package, files = source_tree(tmp_path)
    if kind == "wheel":
        bundled = package_files(files, package)
        bundled[name] = b"bad"
        artifact = write_wheel(tmp_path / "example.whl", bundled)
    else:
        # A raw malicious tar path, rather than one beneath the normal sdist prefix.
        artifact = tmp_path / "example.tar"
        with tarfile.open(artifact, "w") as archive:
            info = tarfile.TarInfo(name)
            info.size = 3
            archive.addfile(info, io.BytesIO(b"bad"))
    problems = check_artifacts(tmp_path, **{kind: artifact})
    assert any("unsafe archive path" in p for p in problems)
    assert not (tmp_path.parent / "escape").exists()


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_duplicate_normalized_members_are_rejected(tmp_path, kind):
    package, files = source_tree(tmp_path)
    name = f"{PACKAGE}/__init__.py"
    if kind == "wheel":
        bundled = package_files(files, package)
        bundled["./" + name] = bundled[name]
        artifact = write_wheel(tmp_path / "example.whl", bundled)
    else:
        files["./" + name] = files[name]
        artifact = write_sdist(tmp_path / "example.tar.gz", files)
    assert any("duplicate archive member" in p
               for p in check_artifacts(tmp_path, **{kind: artifact}))


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_archive_links_are_not_followed(tmp_path, kind):
    package, files = source_tree(tmp_path)
    if kind == "wheel":
        artifact = write_wheel(tmp_path / "example.whl", package_files(files, package))
        with zipfile.ZipFile(artifact, "a") as archive:
            info = zipfile.ZipInfo(f"{PACKAGE}/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
    else:
        artifact = tmp_path / "example.tar"
        with tarfile.open(artifact, "w") as archive:
            info = tarfile.TarInfo("example-1.0/link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            archive.addfile(info)
    assert any("unsupported archive member type" in p
               for p in check_artifacts(tmp_path, **{kind: artifact}))


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_unreadable_and_malformed_archives_return_problems(tmp_path, kind):
    source_tree(tmp_path)
    missing = tmp_path / "missing"
    assert any("cannot validate" in p for p in check_artifacts(tmp_path, **{kind: missing}))
    missing.write_bytes(b"this is not an archive")
    assert any("cannot validate" in p for p in check_artifacts(tmp_path, **{kind: missing}))


def test_truncated_compressed_sdist_returns_problems(tmp_path):
    _, files = source_tree(tmp_path)
    sdist = write_sdist(tmp_path / "example.tar.gz", files)
    sdist.write_bytes(sdist.read_bytes()[:30])
    assert any("cannot validate" in p for p in check_artifacts(tmp_path, sdist=sdist))


@pytest.mark.parametrize("metadata", [None, b"not a metadata header\n", b"Name: example\n"])
def test_missing_or_malformed_sdist_metadata_is_reported(tmp_path, metadata):
    _, files = source_tree(tmp_path)
    sdist = write_sdist(tmp_path / "example.tar.gz", files, metadata=metadata)
    assert any("PKG-INFO" in p for p in check_artifacts(tmp_path, sdist=sdist))


def test_missing_or_malformed_wheel_metadata_is_reported(tmp_path):
    package, files = source_tree(tmp_path)
    bundled = package_files(files, package)
    wheel = write_wheel(tmp_path / "example.whl", bundled, metadata=False)
    assert any(".dist-info" in p for p in check_artifacts(tmp_path, wheel=wheel))
    bundled.update({f"{DIST_INFO}/METADATA": METADATA, f"{DIST_INFO}/WHEEL": b"bad\n",
                    f"{DIST_INFO}/RECORD": b""})
    write_wheel(wheel, bundled, metadata=False)
    assert any("malformed WHEEL metadata" in p for p in check_artifacts(tmp_path, wheel=wheel))


def test_mismatched_distribution_versions_are_reported(tmp_path):
    package, files = source_tree(tmp_path)
    wheel = write_wheel(tmp_path / "example.whl", package_files(files, package))
    sdist = write_sdist(tmp_path / "example.tar.gz", files,
                         metadata=METADATA.replace(b"Version: 1.0", b"Version: 2.0"))
    assert any("wheel and sdist metadata disagree" in p
               for p in check_artifacts(tmp_path, wheel=wheel, sdist=sdist))


def test_source_links_and_traversal_are_rejected(tmp_path):
    package, files = source_tree(tmp_path)
    wheel = write_wheel(tmp_path / "example.whl", package_files(files, package))
    (tmp_path / package / "link").symlink_to(tmp_path / "scripts/regenerate.py")
    assert any("source path is a symlink" in p for p in check_artifacts(tmp_path, wheel=wheel))
    assert any("source path must stay inside" in p for p in check_artifacts(
        tmp_path, wheel=wheel, package_dirs=["../outside"],
    ))


def test_package_cache_files_do_not_become_required_resources(tmp_path):
    package, files = source_tree(tmp_path)
    cache = tmp_path / package / "__pycache__/example.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"local interpreter output")
    wheel = write_wheel(tmp_path / "example.whl", package_files(files, package))
    assert check_artifacts(tmp_path, wheel=wheel) == []


def test_empty_requests_and_missing_declarations_cannot_pass_vacuously(tmp_path):
    assert check_artifacts(tmp_path) == ["provide at least one wheel or sdist to validate"]
    assert "provide package_dirs" in check_artifacts(tmp_path, wheel="unused.whl")[0]
    assert "missing" in check_artifacts(tmp_path, wheel="unused.whl",
                                       package_dirs=["missing"])[0]
    assert check_artifacts(tmp_path, wheel="unused.whl", package_dirs=[]) == [
        "no declared source resources to validate",
    ]
