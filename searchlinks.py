# -*- coding: utf-8 -*-
# CoverUp: MusicBrainz Picard plugin. GPL-2.0-or-later.
"""Build web-search links from an album's tags, for searching by hand in the user's browser.

CoverUp never fetches or scrapes search-engine result pages: these links open in the browser, the user
picks an image, and pastes or drags it back into the review window. Pure Python.
"""

from __future__ import annotations

import re
import urllib.parse

from .model import Query

_BRACKETS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_EDITION = re.compile(
    r"\b("
    r"(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?|deluxe|super deluxe|expanded|anniversary|reissue|re-issue|"
    r"special edition|limited edition|collector'?s edition|bonus tracks?|mono|stereo|live|"
    r"japan(?:ese)?(?: edition| pressing)?|sacd|mfsl|mobile fidelity|half-speed|audiophile|picture disc"
    r")\b",
    re.IGNORECASE,
)


def base_title(album: str) -> str:
    """Album title without bracketed edition notes: 'Abbey Road (Remastered 2009)' -> 'Abbey Road'."""
    t = _BRACKETS.sub("", album or "").strip()
    return t or (album or "").strip()


def edition_words(q: Query) -> list[str]:
    """Edition hints from the title and the release comment (disambiguation), e.g. ['2009 remaster', 'deluxe']."""
    found: list[str] = []
    for text in (q.album, q.comment):
        for m in _EDITION.finditer(text or ""):
            w = m.group(1).lower()
            if not any(w in f or f in w for f in found):  # "remaster" adds nothing to "remastered 2009"
                found.append(w)
    return found


def format_word(fmt: str) -> str:
    """'12\" Vinyl' -> 'Vinyl', '2xCD' -> 'CD'; digital releases have no physical cover to match."""
    w = re.sub(r"[\d\"'×x]+(?=[A-Za-z])|[\d\"']+", " ", fmt or "").split()
    word = " ".join(w)
    return "" if not word or "digital" in word.lower() else word


def _quote(s: str) -> str:
    s = s.replace('"', "").strip()
    return f'"{s}"' if s else ""


def search_terms(q: Query, precise: bool = False) -> str:
    """Search text. Precise adds label, catalogue number and format, which narrows to one pressing."""
    parts = [_quote(q.artist) if q.artist and q.artist.lower() not in ("various artists", "various") else "", _quote(base_title(q.album))]
    if q.year:
        parts.append(str(q.year))
    parts += edition_words(q)
    if precise:
        if q.label and q.label.lower() not in ("[no label]", "not on label"):
            parts.append(_quote(q.label))
        if q.catalog_number and q.catalog_number.lower() != "[none]":
            parts.append(_quote(q.catalog_number))
        fw = format_word(q.format)
        if fw:
            parts.append(fw)
    parts.append("cover")
    return " ".join(p for p in parts if p)


def links(q: Query) -> list[tuple[str, str]]:
    """(menu label, URL) pairs, most useful first."""
    plain = search_terms(q)
    precise = search_terms(q, precise=True)
    enc = urllib.parse.quote_plus
    out = [
        ("Google Images: large", f"https://www.google.com/search?tbm=isch&tbs=isz:l&q={enc(plain)}"),
    ]
    if precise != plain:
        out.append(("Google Images: this pressing (label, catalogue no.)", f"https://www.google.com/search?tbm=isch&tbs=isz:l&q={enc(precise)}"))
    out += [
        ("Bing Images: large", f"https://www.bing.com/images/search?qft=+filterui:imagesize-large&q={enc(plain)}"),
        ("DuckDuckGo Images", f"https://duckduckgo.com/?ia=images&iax=images&q={enc(plain)}"),
    ]
    discogs_q = " ".join(x for x in (q.artist, base_title(q.album), q.catalog_number) if x)
    if q.discogs_release_id:
        out.append(("Discogs: this release's images", f"https://www.discogs.com/release/{q.discogs_release_id}/images"))
    out.append(("Discogs: search releases", f"https://www.discogs.com/search/?type=release&q={enc(discogs_q)}"))
    if q.release_mbid:
        out.append(("MusicBrainz: cover art of this release", f"https://musicbrainz.org/release/{q.release_mbid}/cover-art"))
    return out


_WRAPPED = (("imgurl", "google.", "/imgres"), ("mediaurl", "bing.com", "/images/search"), ("u", "duckduckgo.com", "/iu"))


def unwrap_image_url(url: str) -> str:
    """Turn a search engine's result link (google.com/imgres?imgurl=…, bing …mediaurl=…) into the image URL."""
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = parts.netloc.lower()
    qs = urllib.parse.parse_qs(parts.query)
    for param, h, path in _WRAPPED:
        if h in host and parts.path.startswith(path) and qs.get(param):
            return qs[param][0]
    return url.strip()
