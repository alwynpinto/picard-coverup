"""Provider parsing, matching and Discogs release confidence, against hand-written fixtures that follow
each API's documented response format."""

import struct

import pytest

from coverup.imageinfo import probe
from coverup.model import ArtType, Query, Tier
from coverup.providers import REGISTRY
from coverup.providers.audiodb import parse_album as audiodb_album
from coverup.providers.audiodb import parse_artist as audiodb_artist
from coverup.providers.base import matches, normalize
from coverup.providers.caa import parse_images
from coverup.providers.discogs import parse_release_images, release_confidence
from coverup.providers.fanart import parse_album as fanart_album
from coverup.providers.fanart import parse_artist as fanart_artist
from coverup.providers.fanart import preview_url
from coverup.providers.local import classify, scan_folder
from coverup.providers.musicbrainz import apply_release_json, discogs_id_from_relations, is_mbid
from coverup.providers.stores import parse_deezer, parse_itunes, parse_lastfm
from coverup.providers.websearch import parse_brave, parse_google
from coverup.settings import Settings

Q = Query(artist="Pink Floyd", album="The Dark Side of the Moon", year=1973, barcode="5 099902 894522",
          catalog_number="SHVL 804", track_count=10, medium_count=1, country="GB")

CAA = {
    "release": "https://musicbrainz.org/release/x",
    "images": [
        {"id": 1, "front": True, "back": False, "types": ["Front"], "comment": "", "approved": True,
         "image": "https://coverartarchive.org/release/x/1.jpg",
         "thumbnails": {"250": "https://coverartarchive.org/release/x/1-250.jpg", "500": "u500", "1200": "u1200"}},
        {"id": 2, "front": False, "back": True, "types": ["Back"], "image": "https://coverartarchive.org/release/x/2.jpg", "thumbnails": {}},
        {"id": 3, "front": False, "back": False, "types": ["Medium"], "comment": "Disc 2", "image": "https://c/3.jpg", "thumbnails": {"250": "t3"}},
        {"id": 4, "front": False, "back": False, "types": ["Booklet"], "image": "https://c/4.jpg", "thumbnails": {}},
        {"id": 5, "front": False, "back": False, "types": ["Booklet"], "image": "https://c/5.jpg", "thumbnails": {}},
        {"id": 6, "front": False, "back": False, "types": ["Matrix/Runout"], "image": "https://c/6.jpg", "thumbnails": {}},
    ],
}


def test_registry_has_all_sources():
    assert set(REGISTRY) == {"caa", "discogs", "wikimedia", "fanart", "audiodb", "itunes", "deezer", "lastfm", "websearch", "local"}


def test_caa_types_tiers_and_booklet_pages():
    c = parse_images(CAA, Tier.A)
    types = [x.art_type for x in c]
    assert types == [ArtType.FRONT, ArtType.BACK, ArtType.DISC, ArtType.BOOKLET, ArtType.BOOKLET, ArtType.OTHER]
    assert c[0].thumb_url.endswith("1-250.jpg") and c[0].tier == Tier.A
    assert c[2].comment == "Disc 2"
    assert [x.page for x in c if x.art_type == ArtType.BOOKLET] == [1, 2]


def test_musicbrainz_identity():
    rel = {
        "title": "The Dark Side of the Moon", "barcode": "123", "date": "1973-03-01", "country": "GB",
        "relations": [{"target-type": "url", "type": "discogs", "url": {"resource": "https://www.discogs.com/release/1873013-Pink-Floyd"}}],
        "release-group": {"id": "f5093c06-23e3-404f-aeaa-40f72885ee3a"},
        "artist-credit": [{"name": "Pink Floyd", "joinphrase": "", "artist": {"id": "83d91898-7763-47d7-b03b-b92132375c47"}}],
        "media": [{"format": "Vinyl", "track-count": 10}],
        "label-info": [{"catalog-number": "SHVL 804", "label": {"name": "Harvest"}}],
    }
    assert discogs_id_from_relations(rel) == 1873013
    q = Query(release_mbid="d1e0e6b4-0ec4-4e6f-a32f-1f28bbbb3a9e")
    apply_release_json(q, rel)
    assert (q.discogs_release_id, q.rg_mbid[:8], q.artist, q.medium_count, q.track_count, q.year, q.label) == (
        1873013, "f5093c06", "Pink Floyd", 1, 10, 1973, "Harvest")
    assert is_mbid(q.release_mbid) and not is_mbid("nope")


def discogs_release(**over):
    rel = {
        "id": 1873013, "title": "The Dark Side Of The Moon", "year": 1973, "country": "UK",
        "artists": [{"name": "Pink Floyd"}],
        "identifiers": [{"type": "Barcode", "value": "5099902894522"}],
        "labels": [{"name": "Harvest", "catno": "SHVL 804"}],
        "formats": [{"name": "Vinyl", "qty": "1"}],
        "tracklist": [{"type_": "track"}] * 10,
        "images": [
            {"type": "primary", "uri": "https://i.discogs.com/a.jpg", "uri150": "https://i.discogs.com/a150.jpg", "width": 600, "height": 600},
            {"type": "secondary", "uri": "https://i.discogs.com/b.jpg", "uri150": "https://i.discogs.com/b150.jpg", "width": 600, "height": 590},
        ],
    }
    rel.update(over)
    return rel


def test_discogs_confidence_high_for_matching_release():
    conf, reasons = release_confidence(Q, discogs_release())
    assert conf >= 0.9, reasons


def test_discogs_confidence_low_for_wrong_pressing():
    conf, _ = release_confidence(Q, discogs_release(identifiers=[{"type": "Barcode", "value": "999"}],
                                                    labels=[{"catno": "X-1"}], tracklist=[{"type_": "track"}] * 18, year=2011))
    assert conf < 0.75


def test_discogs_images_primary_is_front_secondary_unlabelled():
    c = parse_release_images(discogs_release(), Tier.A)
    assert c[0].art_type == ArtType.FRONT and c[0].dims_known and c[0].width == 600
    assert c[1].art_type == ArtType.OTHER and c[1].type_confidence < 0.5


def test_fanart_album_and_artist():
    rg = "f5093c06-23e3-404f-aeaa-40f72885ee3a"
    payload = {"albums": {rg: {
        "albumcover": [{"id": "1", "url": "https://assets.fanart.tv/fanart/music/x/albumcover/a.jpg", "likes": "3"}],
        "cdart": [{"id": "2", "url": "https://assets.fanart.tv/fanart/music/x/cdart/d.png", "likes": "1", "disc": "2", "size": "1000"}],
    }}}
    c = fanart_album(payload, rg)
    assert [x.art_type for x in c] == [ArtType.FRONT, ArtType.DISC]
    assert c[1].disc_number == 2 and c[0].likes == 3 and c[0].tier == Tier.B
    assert "/preview/" in c[0].thumb_url
    art = fanart_artist({"hdmusiclogo": [{"id": "9", "url": "u1", "likes": "5"}], "artistthumb": [{"id": "8", "url": "u2"}]})
    assert {x.art_type for x in art} == {ArtType.ARTIST_LOGO, ArtType.ARTIST_THUMB}
    assert preview_url("https://assets.fanart.tv/fanart/a.jpg") == "https://assets.fanart.tv/preview/a.jpg"


def test_audiodb():
    c = audiodb_album({"album": [{"strAlbumThumb": "https://r/t.jpg", "strAlbumThumbBack": "https://r/b.jpg", "strAlbumCDart": "https://r/cd.png"}]}, 1)
    assert [x.art_type for x in c] == [ArtType.FRONT, ArtType.BACK, ArtType.DISC]
    assert c[2].disc_number == 1
    assert audiodb_album({"album": None}, 1) == []
    multi = audiodb_album({"album": [{"strAlbumCDart": "https://r/cd.png"}]}, 2)
    assert multi[0].disc_number is None  # one CD art for a 2-disc album: unknown which disc
    assert audiodb_artist({"artists": [{"strArtistLogo": "https://r/l.png"}]})[0].art_type == ArtType.ARTIST_LOGO


def test_itunes_matching_and_url_rewrite():
    payload = {"results": [
        {"collectionId": 1, "artistName": "Pink Floyd", "collectionName": "The Dark Side of the Moon (2011 Remastered Version)",
         "artworkUrl100": "https://is1.mzstatic.com/image/thumb/x/100x100bb.jpg"},
        {"collectionId": 2, "artistName": "Some Tribute Band", "collectionName": "Dark Side Tribute", "artworkUrl100": "https://x/100x100bb.jpg"},
    ]}
    c = parse_itunes(payload, Q)
    assert len(c) == 1 and c[0].url.endswith("/3000x3000bb.jpg") and c[0].thumb_url.endswith("/250x250bb.jpg")
    assert c[0].tier == Tier.C


def test_deezer_and_lastfm():
    d = parse_deezer({"data": [{"id": 5, "title": "The Dark Side Of The Moon", "artist": {"name": "Pink Floyd"},
                                "cover_xl": "https://e/1000x1000.jpg", "cover_medium": "https://e/250.jpg"}]}, Q)
    assert d[0].width == 1000 and d[0].dims_known
    lf = parse_lastfm({"album": {"name": "The Dark Side of the Moon", "artist": "Pink Floyd", "image": [
        {"size": "large", "#text": "https://lastfm.freetls.fastly.net/i/u/174s/a.png"},
        {"size": "mega", "#text": "https://lastfm.freetls.fastly.net/i/u/300x300/a.png"}]}}, Q)
    assert lf[0].url == "https://lastfm.freetls.fastly.net/i/u/a.png"


def test_web_search_parsers():
    b = parse_brave({"results": [{"title": "t", "properties": {"url": "https://x/a.jpg", "width": 1200, "height": 1200}, "thumbnail": {"src": "https://t/a"}}]})
    assert b[0].width == 1200 and b[0].thumb_url == "https://t/a" and b[0].tier == Tier.C
    g = parse_google({"items": [{"link": "https://x/b.jpg", "image": {"width": 800, "height": 800, "thumbnailLink": "https://t/b"}}]})
    assert g[0].dims_known and g[0].thumb_url == "https://t/b"


def test_providers_needing_keys_report_unavailable():
    s = Settings.from_mapping({})
    for pid in ("discogs", "fanart", "lastfm", "websearch"):
        ok, why = REGISTRY[pid](None, s).available()
        assert not ok and ("key" in why.lower() or "token" in why.lower())
    for pid in ("caa", "audiodb", "itunes", "deezer", "local"):
        assert REGISTRY[pid](None, s).available()[0]


def test_normalize_and_match():
    assert normalize("The Beatles (Remastered) [Deluxe Edition]") == "beatles"
    assert normalize("Björk") == "bjork"
    assert matches(Q, "Pink Floyd", "Dark Side of the Moon") > 0
    assert matches(Q, "Pink Floyd", "The Wall") == 0
    va = Query(artist="Various Artists", album="Now 50")
    assert matches(va, "Various Artists", "Now 50") > 0


def test_local_classification_and_scan(tmp_path):
    assert classify("cover.jpg") == (ArtType.FRONT, None)
    assert classify("Folder.PNG") == (ArtType.FRONT, None)
    assert classify("back.jpg") == (ArtType.BACK, None)
    assert classify("cd2.png") == (ArtType.DISC, 2)
    assert classify("disc 1.jpg") == (ArtType.DISC, 1)
    assert classify("booklet-03.jpg")[0] == ArtType.BOOKLET
    assert classify("random.jpg")[0] == ArtType.OTHER
    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 700, 700) + b"\x08\x02\x00\x00\x00" + b"\x00" * 8
    (tmp_path / "cover.png").write_bytes(png)
    (tmp_path / "covers").mkdir()
    (tmp_path / "covers" / "back.png").write_bytes(png)
    (tmp_path / "notes.txt").write_text("x")
    found = scan_folder(tmp_path)
    assert {(c.art_type, c.width) for c in found} == {(ArtType.FRONT, 700), (ArtType.BACK, 700)}


def test_probe_formats():
    gif = b"GIF89a" + struct.pack("<HH", 320, 200) + b"\x00" * 10
    assert probe(gif) == (320, 200, "gif")
    bmp = b"BM" + b"\x00" * 16 + struct.pack("<ii", 64, -48) + b"\x00" * 10
    assert probe(bmp) == (64, 48, "bmp")
    assert probe(b"garbage" * 5) is None
    assert probe(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 4) is None  # truncated


@pytest.mark.usefixtures("qapp")
def test_probe_real_jpeg_and_png():
    from helpers import make_image

    assert probe(make_image("a", w=640, h=480)) == (640, 480, "jpeg")
    assert probe(make_image("b", w=300, h=500, fmt="png")) == (300, 500, "png")
