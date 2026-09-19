"""Regional authoring must preserve source content and catch stale translations."""
import json

import pytest

from thalovant_skillkit.cli import main
from thalovant_skillkit.regions import sync_regions


@pytest.fixture
def locale(tmp_path):
    package = tmp_path / "thalovant_skill_demo"
    package.mkdir()
    (package / "__init__.py").touch()
    root = package / "locale"
    (root / "en-US/dialog").mkdir(parents=True)
    (root / "en-US/dialog/color.dialog").write_text("Favorite color: {color}.\n")
    (root / "en-US/dialog/hello.dialog").write_text("Hello!\n")
    (root / "supported.json").write_text('{"locales": ["en-US"]}')
    define(root)
    return root


def define(root, **changes):
    region = {"source": "en-US", "overrides": {
        "dialog/color.dialog": "Favourite colour: {color}.\n",
    }} | changes
    (root / "regional.json").write_text(json.dumps({
        "version": 1, "locales": {"en-CA": region},
    }))


def test_build_inherits_text_and_keeps_explicit_regional_wording(locale):
    assert sync_regions(locale)  # A check does not create files.
    assert not (locale / "en-CA").exists()
    assert sync_regions(locale, write=True) == []
    assert sync_regions(locale) == []
    assert (locale / "en-CA/dialog/color.dialog").read_text() == "Favourite colour: {color}.\n"
    assert (locale / "en-CA/dialog/hello.dialog").read_text() == "Hello!\n"
    assert (locale / "en-US/dialog/color.dialog").read_text() == "Favorite color: {color}.\n"
    assert json.loads((locale / "supported.json").read_text())["locales"] == ["en-CA", "en-US"]


def test_source_changes_and_manual_output_edits_are_detected(locale):
    sync_regions(locale, write=True)
    (locale / "en-US/dialog/hello.dialog").write_text("Good morning!\n")
    (locale / "en-CA/dialog/color.dialog").write_text("Accidental edit")
    assert len(sync_regions(locale)) == 2
    assert sync_regions(locale, write=True) == []
    assert sync_regions(locale) == []


@pytest.mark.parametrize("changes", [
    {"source": "fr-FR"}, {"source": "en-CA"}, {"source": "../en-US"},
    {"overrides": {"../outside": "bad"}}, {"overrides": {"/outside": "bad"}},
    {"overrides": {"dialog/color.dialog": "Missing the slot"}},
    {"overrides": {"dialog/typo.dialog": "bad"}}, {"overrides": []},
])
def test_invalid_manifest_fails_before_writes(locale, changes):
    define(locale, **changes)
    assert sync_regions(locale, write=True)
    assert not (locale / "en-CA").exists()


def test_source_deletion_requires_explicit_cleanup(locale):
    sync_regions(locale, write=True)
    (locale / "en-US/dialog/hello.dialog").unlink()
    assert "obsolete" in sync_regions(locale, write=True)[0]
    assert (locale / "en-CA/dialog/hello.dialog").is_file()


def test_symlink_is_not_followed(locale, tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    (locale / "en-CA").symlink_to(external, target_is_directory=True)
    assert sync_regions(locale, write=True)
    assert list(external.iterdir()) == []


def test_cli_and_no_manifest_compatibility(locale):
    root = str(locale.parents[1])
    assert main(["locales", root]) == 1
    assert main(["locales", root, "--write"]) == 0
    assert main(["locales", root]) == 0
    (locale / "regional.json").unlink()
    assert sync_regions(locale) == []


@pytest.mark.parametrize("kind", ["manifest", "root"])
def test_symlinked_authoring_inputs_are_rejected(locale, tmp_path, kind):
    if kind == "manifest":
        manifest = locale / "regional.json"
        outside = tmp_path / "external.json"
        manifest.replace(outside)
        manifest.symlink_to(outside)
    else:
        linked = tmp_path / "linked-locale"
        linked.symlink_to(locale, target_is_directory=True)
        locale = linked
    assert "symlink" in sync_regions(locale, write=True)[0]
    assert not (locale / "en-CA").exists()
