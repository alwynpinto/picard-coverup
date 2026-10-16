"""Artist images through the whole pipeline: the exact-artist source beats a name match, the kinds follow the
settings, and switching artist images off removes them from the search, the choice and the plan."""

import pytest

pytest.importorskip("PyQt6.QtGui", reason="PyQt6 is needed for image tests (pip install PyQt6)")

from coverup import imaging
from coverup.model import ArtType, Query, Tier
from coverup.pipeline import Pipeline
from coverup.settings import Settings
from helpers import FakeHttp, make_image

pytestmark = pytest.mark.usefixtures("qapp")

REL = "11111111-1111-4111-8111-111111111111"
ART = "33333333-3333-4333-8333-333333333333"
UP = "https://upload.wikimedia.org/"


def routes():
    photo, logo = make_image("a", 1500), make_image("c", 800)
    imageinfo = lambda mime, w, h, url: {"query": {"pages": {"1": {"imageinfo": [{  # noqa: E731
        "url": url, "mime": mime, "width": w, "height": h, "thumburl": url + "?t", "thumbwidth": 800, "thumbheight": 800}]}}}}
    return {
        f"https://musicbrainz.org/ws/2/release/{REL}": {"title": "Album", "artist-credit": [{"name": "Band", "artist": {"id": ART}}], "media": [{}]},
        f"https://musicbrainz.org/ws/2/artist/{ART}": {"relations": [{"type": "wikidata", "url": {"resource": "https://www.wikidata.org/wiki/Q9"}}]},
        "https://www.wikidata.org/wiki/Special:EntityData/Q9.json": {"entities": {"Q9": {"claims": {
            "P18": [{"mainsnak": {"datavalue": {"value": "Band.jpg"}}}], "P154": [{"mainsnak": {"datavalue": {"value": "Band logo.svg"}}}]}}}},
        "https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&titles=File%3ABand.jpg":
            imageinfo("image/jpeg", 1500, 1500, UP + "band.jpg"),
        "https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&titles=File%3ABand+logo.svg":
            imageinfo("image/svg+xml", 800, 800, UP + "logo.svg"),
        UP + "band.jpg": photo, UP + "band.jpg?t": photo, UP + "logo.svg?t": logo,
        "https://api.deezer.com/search/album": {"data": []},
        "https://api.deezer.com/search/artist": {"data": [{"id": 4, "name": "Band", "picture_xl": "https://dz/a.jpg", "picture_medium": "https://dz/am.jpg"}]},
        "https://dz/a.jpg": make_image("b", 1000), "https://dz/am.jpg": make_image("b", 250),
        "https://coverartarchive.org/": 404,
    }


def run(**kw):
    s = Settings.from_mapping({"providers_enabled": ["caa", "wikimedia", "deezer"], "http_cache_hours": 0, **kw})
    p = Pipeline(s, FakeHttp(routes()), imaging.fingerprint)
    return p, p.run(Query(artist="Band", album="Album", release_mbid=REL))


def test_the_exact_artist_photo_beats_a_name_match_and_logo_is_offered():
    p, res = run()
    photo = res.artist[ArtType.ARTIST_THUMB]
    assert photo.provider == "wikimedia" and photo.tier == Tier.A
    deezer = [c for c in res.candidates if c.provider == "deezer" and c.art_type == ArtType.ARTIST_THUMB]
    assert deezer and deezer[0].tier == Tier.C  # found, but only a name match
    assert res.artist[ArtType.ARTIST_LOGO].provider == "wikimedia"
    # by default only the photo is applied; the logo is in the dialog for a manual pick
    plan, _notes = p.auto_plan(res)
    assert [(it.art_type, it.candidate.provider) for it in plan if it.art_type in {ArtType.ARTIST_THUMB, ArtType.ARTIST_LOGO}] == [
        (ArtType.ARTIST_THUMB, "wikimedia")]


def test_ticking_logo_and_banner_kinds_changes_the_plan():
    p, res = run(artist_types=["thumb", "logo"])
    kinds = {it.art_type for it in p.auto_plan(res)[0]}
    assert {ArtType.ARTIST_THUMB, ArtType.ARTIST_LOGO} <= kinds


def test_deezer_alone_still_supplies_a_photo_when_nothing_better_exists():
    p, res = run(providers_enabled=["caa", "deezer"])
    assert res.artist[ArtType.ARTIST_THUMB].provider == "deezer"


def test_switching_artist_images_off_removes_them_everywhere():
    p, res = run(artist_art=False)
    assert not [c for c in res.candidates if c.art_type in {ArtType.ARTIST_THUMB, ArtType.ARTIST_LOGO}]
    assert not any(it.art_type == ArtType.ARTIST_THUMB for it in p.auto_plan(res)[0])
    assert not any("search/artist" in u for u in p.http.calls)


def test_unticking_artist_in_apply_types_keeps_them_out_of_the_plan_but_in_the_dialog_pool():
    p, res = run(apply_types=["front", "back"])
    assert res.artist[ArtType.ARTIST_THUMB] is not None  # still found, for the review window
    assert not any(it.art_type in {ArtType.ARTIST_THUMB, ArtType.ARTIST_LOGO} for it in p.auto_plan(res)[0])
