"""File routing (folders, names, presets, artist folder, discs) and safe writing with undo."""

import pytest

pytest.importorskip("PyQt6.QtGui", reason="PyQt6 is needed for image tests (pip install PyQt6)")

import json
from pathlib import Path

import pytest

from coverup import imaging
from coverup.apply import files as F
from coverup.apply.writer import FileItem, FolderPlan, targets_for, write_item
from coverup.model import ArtType, Candidate
from coverup.settings import Settings
from helpers import make_image

pytestmark = pytest.mark.usefixtures("qapp")


def S(**kw):
    return Settings.from_mapping(kw)


def names(targets, base):
    return [str(Path(t.folder).relative_to(base) / t.stem) for t in targets]


def test_default_routing_subfolder_plus_front_in_album_folder(tmp_path):
    album = tmp_path / "Artist" / "Album"
    s = S()
    assert names(targets_for(FileItem(ArtType.FRONT, b""), album, s), tmp_path) == ["Artist/Album/cover", "Artist/Album/covers/cover"]
    assert names(targets_for(FileItem(ArtType.BACK, b""), album, s), tmp_path) == ["Artist/Album/covers/back"]
    assert names(targets_for(FileItem(ArtType.DISC, b"", disc_number=2), album, s), tmp_path) == ["Artist/Album/covers/disc2"]
    assert names(targets_for(FileItem(ArtType.BOOKLET, b"", page=3), album, s), tmp_path) == ["Artist/Album/covers/booklet-03"]
    assert names(targets_for(FileItem(ArtType.ARTIST_THUMB, b""), album, s), tmp_path) == ["Artist/artist"]
    assert names(targets_for(FileItem(ArtType.ARTIST_LOGO, b""), album, s), tmp_path) == ["Artist/logo"]


@pytest.mark.parametrize("folder", ["art", "artwork", "booklet", "My Scans"])
def test_user_defined_folder(tmp_path, folder):
    s = S(folder_name=folder, front_in_album_folder=False)
    assert names(targets_for(FileItem(ArtType.FRONT, b""), tmp_path / "A", s), tmp_path) == [f"A/{folder}/cover"]


def test_same_folder_mode_and_presets(tmp_path):
    s = S(folder_mode="same", naming_preset="kodi")
    assert names(targets_for(FileItem(ArtType.FRONT, b""), tmp_path / "A", s), tmp_path) == ["A/folder"]
    assert names(targets_for(FileItem(ArtType.DISC, b"", disc_number=1), tmp_path / "A", s), tmp_path) == ["A/cdart1"]
    s = S(folder_mode="same", naming_preset="custom", name_front="front-{discnumber}")
    assert names(targets_for(FileItem(ArtType.FRONT, b""), tmp_path / "A", s), tmp_path) == ["A/front-1"]


def test_artist_art_can_be_disabled(tmp_path):
    assert targets_for(FileItem(ArtType.ARTIST_THUMB, b""), tmp_path / "A", S(save_artist_art=False)) == []


def test_invalid_folder_name_is_refused(tmp_path):
    with pytest.raises(ValueError):
        targets_for(FileItem(ArtType.BACK, b""), tmp_path, S(folder_name="../x"))


def test_write_item_respects_file_limits_and_is_always_jpeg(tmp_path):
    big = make_image("a", 2000)
    s = S(file_max_side=1000)
    from coverup.apply.writer import Target

    r = write_item(FileItem(ArtType.FRONT, big), Target(tmp_path, "cover"), s, imaging.prepare, "b1")
    assert r.action == "written" and r.path.name == "cover.jpg"
    assert imaging.size_of(r.path.read_bytes()) == (1000, 1000)


def test_original_bytes_kept_when_no_change_needed(tmp_path):
    data = make_image("a", 800)
    from coverup.apply.writer import Target

    r = write_item(FileItem(ArtType.FRONT, data), Target(tmp_path, "cover"), S(), imaging.prepare, "b1")
    assert r.path.read_bytes() == data


def test_existing_png_is_replaced_by_larger_jpg_and_undo_restores(tmp_path):
    from coverup.apply.writer import Target

    old = make_image("a", 500, fmt="png")
    (tmp_path / "cover.png").write_bytes(old)
    r = write_item(FileItem(ArtType.FRONT, make_image("a", 1200)), Target(tmp_path, "cover"), S(), imaging.prepare, "b7")
    assert r.action in ("written", "replaced") and (tmp_path / "cover.jpg").exists() and not (tmp_path / "cover.png").exists()
    msgs = F.undo_batch(tmp_path, "b7")
    assert (tmp_path / "cover.png").read_bytes() == old and not (tmp_path / "cover.jpg").exists(), msgs


def test_smaller_image_does_not_replace_existing_other_format(tmp_path):
    from coverup.apply.writer import Target

    (tmp_path / "cover.png").write_bytes(make_image("a", 1500, fmt="png"))
    r = write_item(FileItem(ArtType.FRONT, make_image("a", 600)), Target(tmp_path, "cover"), S(), imaging.prepare, "b")
    assert r.action == "skipped" and not (tmp_path / "cover.jpg").exists()


def test_folder_plan_writes_each_thing_once_per_folder_and_discs_to_their_folder(tmp_path):
    cd1, cd2 = tmp_path / "Artist" / "Album" / "CD1", tmp_path / "Artist" / "Album" / "CD2"
    front = Candidate("caa", "1", "u", ArtType.FRONT, width=600, height=600)
    items = [
        FileItem(ArtType.FRONT, make_image("a", 600), front),
        FileItem(ArtType.DISC, make_image("b", 500), None, disc_number=1),
        FileItem(ArtType.DISC, make_image("c", 500), None, disc_number=2),
        FileItem(ArtType.ARTIST_THUMB, make_image("c", 400)),
    ]
    plan = FolderPlan(items, S(folder_mode="same", multi_folder="every"), "batch1")
    plan.write_for_folder(cd1, 1, imaging.prepare)
    again = plan.write_for_folder(cd1, 1, imaging.prepare)  # second track of disc 1
    assert again == []
    plan.write_for_folder(cd2, 2, imaging.prepare)
    assert sorted(p.name for p in cd1.iterdir() if p.is_file()) == ["cover.jpg", "coverup.json", "disc1.jpg"]
    assert sorted(p.name for p in cd2.iterdir() if p.is_file()) == ["cover.jpg", "coverup.json", "disc2.jpg"]
    # disc sub-folders are recognised: the artist image goes to Artist/, once
    assert (tmp_path / "Artist" / "artist.jpg").exists() and not (tmp_path / "Artist" / "Album" / "artist.jpg").exists()
    side = json.loads((cd1 / "coverup.json").read_text())
    assert side["files"]["cover.jpg"]["source"] == "caa"


def test_multi_folder_first_only(tmp_path):
    items = [FileItem(ArtType.FRONT, make_image("a", 600)), FileItem(ArtType.DISC, make_image("b", 500), disc_number=2)]
    plan = FolderPlan(items, S(folder_mode="same", multi_folder="first", write_sidecar=False), "b")
    plan.write_for_folder(tmp_path / "CD1", 1, imaging.prepare)
    plan.write_for_folder(tmp_path / "CD2", 2, imaging.prepare)
    assert (tmp_path / "CD1" / "cover.jpg").exists() and not (tmp_path / "CD2" / "cover.jpg").exists()
    assert (tmp_path / "CD2" / "disc2.jpg").exists()  # disc art always goes with its disc


def test_undo_batch_only_touches_its_batch(tmp_path):
    F.safe_write(tmp_path / "a.jpg", b"1", batch="x")
    F.safe_write(tmp_path / "b.jpg", b"2", batch="y")
    assert F.last_batch(tmp_path) == "y"
    F.undo_batch(tmp_path, "x")
    assert not (tmp_path / "a.jpg").exists() and (tmp_path / "b.jpg").exists()


def test_generated_provenance_in_sidecar(tmp_path):
    c = Candidate("generated", "g", "", ArtType.FRONT, generated=True)
    c.extra.update({"method": "template", "template": "fantasy", "seed": 42})
    plan = FolderPlan([FileItem(ArtType.FRONT, make_image("a", 600), c)], S(folder_mode="same"), "b")
    plan.write_for_folder(tmp_path, 1, imaging.prepare)
    rec = json.loads((tmp_path / "coverup.json").read_text())["files"]["cover.jpg"]
    assert rec["generated"] is True and rec["template"] == "fantasy" and rec["seed"] == 42
