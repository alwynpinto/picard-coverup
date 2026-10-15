"""End-to-end pipeline runs against a fake web, with real Qt image fingerprints."""

import pytest

pytest.importorskip("PyQt6.QtGui", reason="PyQt6 is needed for image tests (pip install PyQt6)")

import pytest

from coverup import imaging
from coverup.model import ArtType, Query, Tier
from coverup.pipeline import Pipeline
from coverup.settings import Settings
from helpers import FakeHttp, make_image

pytestmark = pytest.mark.usefixtures("qapp")

REL = "11111111-1111-4111-8111-111111111111"
RG = "22222222-2222-4222-8222-222222222222"
ART = "33333333-3333-4333-8333-333333333333"


def mb_release(media=1, discogs=None):
    rel = {
        "title": "Album", "release-group": {"id": RG},
        "artist-credit": [{"name": "Artist", "artist": {"id": ART}}],
        "media": [{"format": "CD", "track-count": 10}] * media,
        "relations": [],
    }
    if discogs:
        rel["relations"].append({"target-type": "url", "type": "discogs", "url": {"resource": f"https://www.discogs.com/release/{discogs}"}})
    return rel


def caa(front_url, back_url=None, discs=()):
    imgs = [{"id": 1, "front": True, "types": ["Front"], "image": front_url, "thumbnails": {"250": front_url}}]
    if back_url:
        imgs.append({"id": 2, "back": True, "types": ["Back"], "image": back_url, "thumbnails": {"250": back_url}})
    for i, (u, comment) in enumerate(discs):
        imgs.append({"id": 10 + i, "types": ["Medium"], "comment": comment, "image": u, "thumbnails": {"250": u}})
    return {"images": imgs}


def deezer(url):
    return {"data": [{"id": 9, "title": "Album", "artist": {"name": "Artist"}, "cover_xl": url, "cover_medium": url}]}


def itunes(url):
    return {"results": [{"collectionId": 7, "artistName": "Artist", "collectionName": "Album", "artworkUrl100": url + "/100x100bb.jpg"}]}


def settings(**kw):
    base = {"providers_enabled": ["caa", "deezer", "itunes", "discogs"], "discogs_token": "tok", "http_cache_hours": 0}
    base.update(kw)
    return Settings.from_mapping(base)


def run(routes, q=None, **kw):
    http = FakeHttp(routes)
    p = Pipeline(settings(**kw), http, imaging.fingerprint)
    res = p.run(q or Query(artist="Artist", album="Album", release_mbid=REL))
    return p, res, http


def test_exact_release_wins_and_is_auto_applied():
    A, B = make_image("a", 1200), make_image("b", 1000)
    routes = {
        f"https://musicbrainz.org/ws/2/release/{REL}": mb_release(),
        f"https://coverartarchive.org/release/{REL}": caa("https://caa/front.jpg", "https://caa/back.jpg"),
        f"https://coverartarchive.org/release-group/{RG}": 404,
        "https://caa/front.jpg": A, "https://caa/back.jpg": make_image("c", 1000),
        "https://api.deezer.com/": deezer("https://dz/x.jpg"), "https://dz/x.jpg": A,
        "https://itunes.apple.com/": itunes("https://it/y"), "https://it/y": B,
        "https://api.discogs.com/database/search": {"results": []},
    }
    p, res, _ = run(routes)
    front = res.selections[ArtType.FRONT]
    assert front.winner.provider == "caa" and front.winner.tier == Tier.A
    assert front.auto_apply and not front.conflict
    assert front.winner.width == 1200  # measured from the image header
    # deezer has the same artwork: they cluster together
    assert any(len(cl.providers) == 2 for cl in front.clusters)
    plan, notes = p.auto_plan(res, {ArtType.FRONT, ArtType.BACK})
    assert [(i.art_type, i.candidate.provider) for i in plan] == [(ArtType.FRONT, "caa"), (ArtType.BACK, "caa")]
    assert res.provider_status["discogs"] == "0 found"


def test_no_anchor_consensus_wins():
    A = make_image("a", 1000)
    routes = {
        f"https://musicbrainz.org/ws/2/release/{REL}": mb_release(),
        "https://coverartarchive.org/": 404,
        "https://api.deezer.com/": deezer("https://dz/x.jpg"), "https://dz/x.jpg": A,
        "https://itunes.apple.com/": itunes("https://it/y"), "https://it/y": A,
        "https://api.discogs.com/database/search": {"results": []},
    }
    p, res, _ = run(routes, providers_enabled=["caa", "deezer", "itunes"])
    front = res.selections[ArtType.FRONT]
    assert front.winner.provider in ("deezer", "itunes")
    assert front.auto_apply and "visual-agreement" in front.rationale


def test_conflict_is_not_auto_applied():
    A, B = make_image("a", 1200), make_image("b", 1000)
    routes = {
        f"https://musicbrainz.org/ws/2/release/{REL}": mb_release(),
        f"https://coverartarchive.org/release/{REL}": caa("https://caa/front.jpg"),
        f"https://coverartarchive.org/release-group/{RG}": 404,
        "https://caa/front.jpg": A,
        "https://api.deezer.com/": deezer("https://dz/x.jpg"), "https://dz/x.jpg": B,
        "https://itunes.apple.com/": itunes("https://it/y"), "https://it/y": B,
    }
    p, res, _ = run(routes, providers_enabled=["caa", "deezer", "itunes"], conflict_min_sources=2)
    assert res.selections[ArtType.FRONT].conflict
    plan, notes = p.auto_plan(res, {ArtType.FRONT})
    assert plan == [] and any("Conflict" in n for n in notes)


def test_below_apply_minimum_triggers_creative_and_is_not_applied():
    small = make_image("a", 400)
    routes = {
        f"https://musicbrainz.org/ws/2/release/{REL}": mb_release(),
        f"https://coverartarchive.org/release/{REL}": caa("https://caa/front.jpg"),
        f"https://coverartarchive.org/release-group/{RG}": 404,
        "https://caa/front.jpg": small,
    }
    p, res, _ = run(routes, providers_enabled=["caa"], min_front=300, apply_min_side=500, creative_triggers=["below_min"])
    assert res.selections[ArtType.FRONT].winner.width == 400
    plan, notes = p.auto_plan(res, {ArtType.FRONT})
    assert plan == [] and "below the 500px apply minimum" in notes[0]
    go, why = res.creative[ArtType.FRONT]
    assert go and "below" in why


def test_search_minimum_rejects_small_and_explains():
    routes = {
        f"https://musicbrainz.org/ws/2/release/{REL}": mb_release(),
        f"https://coverartarchive.org/release/{REL}": caa("https://caa/front.jpg"),
        f"https://coverartarchive.org/release-group/{RG}": 404,
        "https://caa/front.jpg": make_image("a", 250),
    }
    _p, res, _ = run(routes, providers_enabled=["caa"])
    sel = res.selections[ArtType.FRONT]
    assert sel.winner is None and sel.rejected[0].rejected_reason.startswith("Too small")


def test_disc_art_assigned_per_disc():
    routes = {
        f"https://musicbrainz.org/ws/2/release/{REL}": mb_release(media=2),
        f"https://coverartarchive.org/release/{REL}": caa("https://caa/f.jpg", discs=[("https://caa/d1.jpg", "Disc 1"), ("https://caa/d2.jpg", "CD2")]),
        f"https://coverartarchive.org/release-group/{RG}": 404,
        "https://caa/f.jpg": make_image("a", 1000), "https://caa/d1.jpg": make_image("c", 800), "https://caa/d2.jpg": make_image("b", 800),
    }
    p, res, _ = run(routes, providers_enabled=["caa"])
    assert res.query.medium_count == 2
    assert res.discs[1].winner.url.endswith("d1.jpg") and res.discs[2].winner.url.endswith("d2.jpg")
    plan, _ = p.auto_plan(res, {ArtType.DISC})
    assert [(i.disc_number, i.candidate.url[-6:]) for i in plan] == [(1, "d1.jpg"), (2, "d2.jpg")]


def test_discogs_linked_release_is_tier_a():
    routes = {
        f"https://musicbrainz.org/ws/2/release/{REL}": mb_release(discogs=555),
        "https://api.discogs.com/releases/555": {"id": 555, "title": "Album", "artists": [{"name": "Artist"}],
                                                 "images": [{"type": "primary", "uri": "https://dg/p.jpg", "uri150": "https://dg/p.jpg", "width": 900, "height": 900}]},
        "https://dg/p.jpg": make_image("a", 900),
    }
    _p, res, http = run(routes, providers_enabled=["discogs"])
    w = res.selections[ArtType.FRONT].winner
    assert w.provider == "discogs" and w.tier == Tier.A and w.extra["discogs_found_via"] == "MusicBrainz URL relationship"


def test_broken_provider_does_not_break_the_run():
    routes = {
        f"https://musicbrainz.org/ws/2/release/{REL}": mb_release(),
        "https://coverartarchive.org/": 503,
        "https://api.deezer.com/": deezer("https://dz/x.jpg"), "https://dz/x.jpg": make_image("a", 1000),
    }
    _p, res, _ = run(routes, providers_enabled=["caa", "deezer"])
    assert res.provider_status["caa"].startswith("error")
    assert res.selections[ArtType.FRONT].winner.provider == "deezer"


def test_cancel_stops_the_run():
    http = FakeHttp({})
    http.cancel.set()
    res = Pipeline(settings(), http, imaging.fingerprint).run(Query(artist="A", album="B", release_mbid=REL))
    assert res.cancelled


def test_fetch_full_measures_real_size():
    data = make_image("a", 777)
    http = FakeHttp({"https://x/full.jpg": data})
    from coverup.model import Candidate

    c = Candidate("caa", "1", "https://x/full.jpg")
    Pipeline(settings(), http, imaging.fingerprint).fetch_full(c)
    assert (c.width, c.height, c.bytes) == (777, 777, len(data))
