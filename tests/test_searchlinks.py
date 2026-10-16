"""Hand-search links built from album tags, and unwrapping search-engine result links."""

import urllib.parse

from coverup.model import Query
from coverup.searchlinks import base_title, edition_words, links, search_terms, store_links, store_terms, unwrap_image_url

Q = Query(artist="The Beatles", album="Abbey Road (Remastered 2009)", year=1969, label="Apple Records",
          catalog_number="PCS 7088", format="12\" Vinyl", comment="2009 stereo remaster", release_mbid="m-1", discogs_release_id=123)


def test_base_title_and_edition_words():
    assert base_title(Q.album) == "Abbey Road"
    assert base_title("(What's the Story) Morning Glory?") == "Morning Glory?"
    assert base_title("()") == "()"
    words = edition_words(Q)
    assert "remastered 2009" in words and "stereo" in words


def test_plain_and_precise_terms():
    plain = search_terms(Q)
    assert plain.startswith('"The Beatles" "Abbey Road" 1969') and plain.endswith("cover")
    assert "Apple" not in plain
    precise = search_terms(Q, precise=True)
    assert '"Apple Records"' in precise and '"PCS 7088"' in precise and "Vinyl" in precise
    assert precise.count('"') % 2 == 0  # no stray quote mark from 12" Vinyl
    assert edition_words(Q) == ["remastered 2009", "stereo"]


def test_format_word():
    from coverup.searchlinks import format_word

    assert format_word('12" Vinyl') == "Vinyl" and format_word("2xCD") == "CD" and format_word("CD") == "CD"
    assert format_word("Digital Media") == "" and format_word("") == ""


def test_various_artists_and_placeholders_are_left_out():
    va = Query(artist="Various Artists", album="Now 50", label="[no label]", catalog_number="[none]")
    t = search_terms(va, precise=True)
    assert "Various" not in t and "[no label]" not in t and "[none]" not in t and '"Now 50"' in t


def test_links_cover_the_main_places():
    got = dict(links(Q))
    google = got["Google Images: large"]
    assert google.startswith("https://www.google.com/search?tbm=isch&tbs=isz:l&q=")
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(google).query)["q"][0] == search_terms(Q)
    assert "this pressing" in " ".join(got)
    assert got["Discogs: this release's images"] == "https://www.discogs.com/release/123/images"
    assert got["MusicBrainz: cover art of this release"] == "https://musicbrainz.org/release/m-1/cover-art"
    assert any(k.startswith("Bing") for k in got) and any(k.startswith("DuckDuckGo") for k in got)


def test_unwrap_search_result_links():
    g = "https://www.google.com/imgres?imgurl=https%3A%2F%2Fexample.com%2Fa.jpg&imgrefurl=https%3A%2F%2Fexample.com%2F"
    assert unwrap_image_url(g) == "https://example.com/a.jpg"
    b = "https://www.bing.com/images/search?view=detailV2&mediaurl=https%3A%2F%2Fcdn.x%2Fb.png"
    assert unwrap_image_url(b) == "https://cdn.x/b.png"
    assert unwrap_image_url(" https://example.com/c.jpg ") == "https://example.com/c.jpg"


def test_store_links_use_plain_artist_and_title():
    assert store_terms(Q) == "The Beatles Abbey Road"
    assert store_terms(Query(artist="Various Artists", album="Now 50")) == "Now 50"
    got = dict(store_links(Q))
    assert set(got) == {"Amazon", "Spotify", "Tidal", "Apple Music", "YouTube Music", "Bandcamp", "Qobuz"}
    assert got["Spotify"] == "https://open.spotify.com/search/The%20Beatles%20Abbey%20Road/albums"
    assert got["Tidal"] == "https://tidal.com/search?q=The+Beatles+Abbey+Road"
    assert all(u.startswith("https://") for u in got.values())
