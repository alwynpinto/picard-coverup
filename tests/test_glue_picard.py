"""Integration with real Picard 3 objects (Album, Track, File, CoverArtImage, CoverArtSetter).

Runs only when a Picard 3 source tree is importable (set PICARD_SRC); uses Picard's own test helpers."""

import os
import sys

import pytest

from conftest import have_picard

pytestmark = [pytest.mark.skipif(not have_picard(), reason="set PICARD_SRC to a Picard 3 source tree"), pytest.mark.usefixtures("qapp")]

REL = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def picard_env(tmp_path, monkeypatch):
    sys.path.insert(0, os.environ["PICARD_SRC"])
    from unittest.mock import patch

    from test.picardtestcase import MockTagger, PicardTestCase

    tagger = MockTagger()
    PicardTestCase.init_config()
    PicardTestCase.set_config_values(setting={
        "save_images_to_tags": True, "embed_only_one_front_image": False, "save_images_to_files": False,
        "remove_images_from_tags": False, "save_only_one_front_image": False, "enabled_plugins": [],
        "clear_existing_tags": False, "compare_ignore_tags": [], "nat_name": "[standalone recordings]", "preserve_images": False,
    })
    patches = [patch(f"{m}.tagger_instance", return_value=tagger) for m in ("picard.item", "picard.file", "picard.album", "picard.track")]
    started = []
    for p in patches:
        try:
            p.start()
            started.append(p)
        except AttributeError:
            pass
    monkeypatch.setenv("PICARD_CACHE_DIR", str(tmp_path / "cache"))
    yield tmp_path
    for p in started:
        p.stop()


def build_album(tmp_path, discs=2):
    from picard.album import Album
    from picard.file import File
    from picard.track import Track

    album = Album(REL)
    md = album.metadata
    md["album"] = "Album"
    md["albumartist"] = "Artist"
    md["musicbrainz_albumid"] = REL
    md["musicbrainz_releasegroupid"] = "22222222-2222-4222-8222-222222222222"
    md["musicbrainz_albumartistid"] = "33333333-3333-4333-8333-333333333333"
    md["date"] = "1999-05-01"
    md["totaldiscs"] = str(discs)
    md["barcode"] = "0123"
    files = []
    for d in range(1, discs + 1):
        folder = tmp_path / "Artist" / "Album" / f"CD{d}"
        folder.mkdir(parents=True)
        t = Track(f"t{d}", album)
        t.metadata["discnumber"] = str(d)
        album.tracks.append(t)
        f = File(str(folder / f"0{d}.flac"))
        f.metadata["discnumber"] = f"{d}/{discs}"
        t.files.append(f)
        f.parent_item = t
        files.append(f)
    return album, files


def test_query_from_real_album(picard_env):
    from coverup import glue

    album, files = build_album(picard_env)
    q = glue.query_from(album)
    assert (q.artist, q.album, q.year, q.medium_count, q.release_mbid, q.barcode) == ("Artist", "Album", 1999, 2, REL, "0123")
    assert len(q.album_dirs) == 2
    assert glue.unique_targets([files[0], album, album.tracks[1]]) == [album]


def test_embed_front_on_album_and_disc_art_only_on_its_disc(picard_env):
    from helpers import make_image

    from coverup import glue
    from coverup.model import ArtType, Candidate, Tier
    from coverup.pipeline import PlanItem
    from coverup.settings import Settings

    album, files = build_album(picard_env)
    front = Candidate("caa", "1", "https://caa/f.jpg", ArtType.FRONT, Tier.A, data=make_image("a", 2000))
    disc2 = Candidate("fanart", "2", "https://f/d.png", ArtType.DISC, Tier.B, disc_number=2, data=make_image("b", 800, fmt="png"))
    s = Settings.from_mapping({"embed_max_side": 1000, "record_source_in_comment": True})
    glue.embed(album, [PlanItem(ArtType.FRONT, front), PlanItem(ArtType.DISC, disc2, disc_number=2)], s)
    imgs = list(album.metadata.images)
    fronts = [i for i in imgs if i.is_front_image()]
    assert len(fronts) == 1 and fronts[0].types == ["front"] and fronts[0].can_be_saved_to_disk is False
    assert fronts[0].width == 1000  # resized for embedding
    assert "CoverUp: caa" in fronts[0].comment
    f1_types = [i.types for i in files[0].metadata.images]
    f2_types = [i.types for i in files[1].metadata.images]
    assert ["medium"] not in f1_types and ["medium"] in f2_types
    assert ["front"] in f1_types and ["front"] in f2_types
    # applying again replaces instead of piling up
    glue.embed(album, [PlanItem(ArtType.FRONT, front)], s)
    assert len([i for i in album.metadata.images if i.is_front_image()]) == 1


def test_files_written_after_save_into_final_folders_and_undo(picard_env):
    from helpers import make_image

    from coverup import glue
    from coverup.model import ArtType, Candidate, Tier
    from coverup.pipeline import PlanItem
    from coverup.settings import Settings

    album, files = build_album(picard_env)
    s = Settings.from_mapping({"folder_mode": "subfolder", "folder_name": "artwork", "front_in_album_folder": True})
    items = [
        PlanItem(ArtType.FRONT, Candidate("caa", "1", "u1", ArtType.FRONT, Tier.A, data=make_image("a", 800))),
        PlanItem(ArtType.DISC, Candidate("caa", "2", "u2", ArtType.DISC, Tier.A, data=make_image("b", 600)), disc_number=1),
        PlanItem(ArtType.ARTIST_THUMB, Candidate("fanart", "3", "u3", ArtType.ARTIST_THUMB, Tier.B, data=make_image("c", 600))),
    ]
    glue.apply_plan(album, items, s, embed_on=False, files_on=True)
    cd1 = os.path.dirname(files[0].filename)
    assert not os.path.exists(os.path.join(cd1, "cover.jpg"))  # nothing until Picard saves
    glue.on_file_saved(None, files[0])
    glue.on_file_saved(None, files[1])
    cd2 = os.path.dirname(files[1].filename)
    assert os.path.exists(os.path.join(cd1, "cover.jpg")) and os.path.exists(os.path.join(cd1, "artwork", "cover.jpg"))
    assert os.path.exists(os.path.join(cd1, "artwork", "disc1.jpg")) and not os.path.exists(os.path.join(cd2, "artwork", "disc1.jpg"))
    artist = picard_env / "Artist" / "artist.jpg"
    assert artist.exists()
    assert album.metadata["_coverup_status"] == "applied" and album.metadata["_coverup_source"] == "caa"
    msgs = glue.undo_last(album)
    assert msgs and not os.path.exists(os.path.join(cd1, "cover.jpg")) and not artist.exists()


def test_undo_after_restart_uses_only_this_albums_batch(picard_env):
    from helpers import make_image

    from coverup import glue
    from coverup.apply import files as F
    from coverup.model import ArtType, Candidate, Tier
    from coverup.pipeline import PlanItem
    from coverup.settings import Settings

    album, files = build_album(picard_env, discs=1)
    s = Settings.from_mapping({"folder_mode": "same"})
    glue.apply_plan(album, [PlanItem(ArtType.FRONT, Candidate("caa", "1", "u", ArtType.FRONT, Tier.A, data=make_image("a", 800)))], s, False, True)
    glue.on_file_saved(None, files[0])
    # another album later wrote into the shared artist folder
    F.safe_write(picard_env / "Artist" / "logo.png", b"other album", batch="other")
    glue.STATE.last_batch.clear()  # simulate a Picard restart
    msgs = glue.undo_last(album)
    assert msgs and not os.path.exists(os.path.join(os.path.dirname(files[0].filename), "cover.jpg"))
    assert (picard_env / "Artist" / "logo.png").read_bytes() == b"other album"


def test_disc_art_replaces_only_on_discs_being_updated(picard_env):
    from helpers import make_image

    from coverup import glue
    from coverup.model import ArtType, Candidate, Tier
    from coverup.pipeline import PlanItem
    from coverup.settings import Settings

    album, files = build_album(picard_env)
    s = Settings.from_mapping({})
    d1 = Candidate("caa", "d1", "u1", ArtType.DISC, Tier.A, data=make_image("b", 600))
    d2 = Candidate("caa", "d2", "u2", ArtType.DISC, Tier.A, data=make_image("c", 600))
    glue.embed(album, [PlanItem(ArtType.DISC, d1, disc_number=1), PlanItem(ArtType.DISC, d2, disc_number=2)], s)
    glue.embed(album, [PlanItem(ArtType.DISC, d2, disc_number=2)], s)
    assert [i.types for i in files[0].metadata.images] == [["medium"]]  # disc 1 art kept
    assert [i.types for i in files[1].metadata.images] == [["medium"]]  # disc 2 replaced, not duplicated
