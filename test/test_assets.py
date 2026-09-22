from pathlib import Path

from thalovant_skillkit.assets import bundled_files


def test_asset_cache_avoids_filesystem_work_and_reload_sees_new_files(tmp_path, monkeypatch):
    bundled_files.cache_clear()
    (tmp_path / "a.ogg").touch()
    expected = bundled_files(tmp_path, "*.ogg")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "glob", lambda *a: (_ for _ in ()).throw(AssertionError("rescanned")))
        assert bundled_files(tmp_path, "*.ogg") is expected
    (tmp_path / "b.ogg").touch()
    bundled_files.cache_clear()
    assert [path.name for path in bundled_files(tmp_path, "*.ogg")] == ["a.ogg", "b.ogg"]
    assert bundled_files.cache_info().maxsize == 128
