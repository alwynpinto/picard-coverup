import json

import pytest

from coverup.apply import files as f


def test_sanitize_filename():
    assert f.sanitize_filename('a<b>:c"d/e\\f|g?h*') == "a_b__c_d_e_f_g_h_"
    assert f.sanitize_filename("con") == "_con"
    assert f.sanitize_filename("  trailing. ") == "trailing"
    assert f.sanitize_filename("") == "_"
    assert len(f.sanitize_filename("x" * 500)) == f.MAX_NAME


@pytest.mark.parametrize("name", ["covers", "art", "artwork", "booklet", "My Scans", "ünïcode"])
def test_valid_folder_names(name):
    assert f.validate_folder_name(name) == name


@pytest.mark.parametrize("name", ["", " ", "a/b", "a\\b", "..", ".", "bad:name", "trail.", "con", " lead"])
def test_invalid_folder_names(name):
    with pytest.raises(ValueError):
        f.validate_folder_name(name)


def test_presets_are_all_valid_and_default_is_covers():
    assert f.DEFAULT_FOLDER == "covers"
    for p in f.FOLDER_PRESETS:
        f.validate_folder_name(p)


def test_render_name_templates():
    assert f.render_name("disc{discnumber}", {"discnumber": 2}) == "disc2"
    assert f.render_name("booklet-{n}", {"n": "01"}) == "booklet-01"
    assert f.render_name("{n}/x", {"n": 1}) == "1_x"
    with pytest.raises(ValueError):
        f.render_name("{nope}", {})


def test_resolve_target_dir(tmp_path):
    assert f.resolve_target_dir(tmp_path, None) == tmp_path
    assert f.resolve_target_dir(tmp_path, "covers") == tmp_path / "covers"
    with pytest.raises(ValueError):
        f.resolve_target_dir(tmp_path, "../escape")


def dims_table(table):
    return lambda p: table.get(p.name)


def test_new_file_is_written_atomically_and_journaled(tmp_path):
    res = f.safe_write(tmp_path / "covers" / "cover.jpg", b"jpegdata", (1000, 1000))
    assert res.action == "written" and (tmp_path / "covers" / "cover.jpg").read_bytes() == b"jpegdata"
    assert not list((tmp_path / "covers").glob("*.tmp"))
    journal = (tmp_path / "covers" / f.BACKUP_DIR_NAME / f.JOURNAL_NAME).read_text().splitlines()
    assert json.loads(journal[0])["action"] == "written"


def test_if_better_replaces_only_larger_and_backs_up(tmp_path):
    p = tmp_path / "cover.jpg"
    p.write_bytes(b"old")
    dims = dims_table({"cover.jpg": (500, 500)})
    worse = f.safe_write(p, b"smaller", (300, 300), f.IF_BETTER, dims)
    assert worse.action == "skipped" and p.read_bytes() == b"old"
    better = f.safe_write(p, b"bigger", (1000, 1000), f.IF_BETTER, dims)
    assert better.action == "replaced" and p.read_bytes() == b"bigger"
    assert better.backup and better.backup.read_bytes() == b"old"


def test_if_better_is_conservative_when_sizes_unknown(tmp_path):
    p = tmp_path / "cover.jpg"
    p.write_bytes(b"old")
    assert f.safe_write(p, b"new", None, f.IF_BETTER, lambda _p: None).action == "skipped"
    assert f.safe_write(p, b"new", (10, 10), f.IF_BETTER, lambda _p: None).action == "skipped"


def test_skip_overwrite_and_keep_both_policies(tmp_path):
    p = tmp_path / "cover.jpg"
    p.write_bytes(b"old")
    assert f.safe_write(p, b"x", policy=f.SKIP).action == "skipped"
    both = f.safe_write(p, b"second", policy=f.KEEP_BOTH)
    assert both.action == "kept_both" and both.path.name == "cover-2.jpg" and p.read_bytes() == b"old"
    over = f.safe_write(p, b"over", policy=f.OVERWRITE)
    assert over.action == "replaced" and p.read_bytes() == b"over" and over.backup


def test_validation_failure_writes_nothing(tmp_path):
    res = f.safe_write(tmp_path / "cover.jpg", b"junk", validate=lambda d: False)
    assert res.action == "skipped" and not (tmp_path / "cover.jpg").exists()


def test_failed_write_leaves_no_temp_file(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(f.os, "replace", boom)
    with pytest.raises(OSError):
        f.safe_write(tmp_path / "cover.jpg", b"data")
    assert not list(tmp_path.glob("*.tmp")) and not (tmp_path / "cover.jpg").exists()


def test_unknown_policy_rejected(tmp_path):
    with pytest.raises(ValueError):
        f.safe_write(tmp_path / "a.jpg", b"x", policy="nope")


def test_undo_restores_backup_and_removes_new_files(tmp_path):
    p = tmp_path / "cover.jpg"
    p.write_bytes(b"old")
    f.safe_write(p, b"new", policy=f.OVERWRITE)
    f.safe_write(tmp_path / "back.jpg", b"back")
    out = f.undo_last(tmp_path, 2)
    assert len(out) == 2
    assert p.read_bytes() == b"old" and not (tmp_path / "back.jpg").exists()
    assert f.undo_last(tmp_path, 1) == []


def test_written_files_are_readable_by_other_users(tmp_path):
    """mkstemp() makes 0600 files; media servers running as another user must still read the art."""
    import os
    import stat

    old_umask = os.umask(0o022)
    try:
        new = tmp_path / "cover.jpg"
        f.safe_write(new, b"x" * 10)
        assert stat.S_IMODE(new.stat().st_mode) == 0o644

        existing = tmp_path / "folder.jpg"
        existing.write_bytes(b"old")
        existing.chmod(0o664)
        f.safe_write(existing, b"y" * 10, policy=f.OVERWRITE)
        assert stat.S_IMODE(existing.stat().st_mode) == 0o664
    finally:
        os.umask(old_umask)
