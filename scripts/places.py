"""Look up restaurant details from a Google Maps link.

Lookup chain (first hit wins for each field):
  1. Public Google Maps place page and the place-panel data it links to
  2. OpenStreetMap Nominatim    -- reverse geocoding, address only

No API keys or Google Cloud account are needed.

Coordinates always come from the resolved Google Maps URL itself.
"""
from __future__ import annotations

import html
import io
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote_plus, urlparse

import requests

log = logging.getLogger("places")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
# Nominatim's usage policy asks for an identifying User-Agent.
NOMINATIM_UA = "eathalal-site-builder (+https://github.com/zslabs-fi/eathalal)"
TIMEOUT = 20


@dataclass
class Place:
    name: str | None = None
    lat: float | None = None
    lng: float | None = None
    feature_id: str | None = None
    address: str | None = None
    image_url: str | None = None
    categories: list[str] | None = None
    rating: float | None = None
    reviews: int | None = None
    website: str | None = None
    phone: str | None = None
    resolved_url: str | None = None
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8,fi;q=0.6"})
    # Pre-accept Google's EU cookie consent so we get the real page, not the consent wall.
    s.cookies.set("SOCS", "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg", domain=".google.com")
    s.cookies.set("CONSENT", "YES+cb", domain=".google.com")
    return s


# ---------------------------------------------------------------------------
# URL handling
# ---------------------------------------------------------------------------

_JS_REDIRECT = re.compile(r"https://www\.google\.[a-z.]+/maps/[^\"'<>\s\\]+")


def resolve_url(session: requests.Session, url: str) -> str:
    """Follow a maps.app.goo.gl / goo.gl short link to the full Google Maps URL."""
    host = urlparse(url).netloc
    if "goo.gl" not in host:
        return url
    r = session.get(url, allow_redirects=True, timeout=TIMEOUT)
    final = r.url
    if "/maps" in urlparse(final).path:
        return final
    # Some short links answer 200 with a JS/meta redirect instead of a 30x.
    m = _JS_REDIRECT.search(html.unescape(r.text))
    if m:
        return m.group(0).replace("\\u0026", "&")
    return final


_RE_3D4D = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
_RE_AT = re.compile(r"/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_RE_FID = re.compile(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")
_RE_LATLNG = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def parse_maps_url(url: str) -> Place:
    """Extract name, coordinates and feature id from a full Google Maps URL."""
    p = Place(resolved_url=url)
    parsed = urlparse(url)
    path = parsed.path

    m = re.search(r"/maps/place/([^/@]+)", path)
    if m:
        name = unquote_plus(m.group(1)).strip()
        if not _RE_LATLNG.match(name):
            p.name = name

    # The place pin (!3d!4d) is more accurate than the viewport centre (@lat,lng).
    m = _RE_3D4D.search(url) or _RE_AT.search(path)
    if m:
        p.lat, p.lng = float(m.group(1)), float(m.group(2))

    m = _RE_FID.search(url)
    if m:
        p.feature_id = m.group(1).lower()

    qs = parse_qs(parsed.query)
    for key in ("q", "query", "ll"):
        if key in qs and p.lat is None:
            m = _RE_LATLNG.match(qs[key][0])
            if m:
                p.lat, p.lng = float(m.group(1)), float(m.group(2))
            elif key != "ll" and not p.name:
                p.name = qs[key][0]
    return p


# ---------------------------------------------------------------------------
# Google Maps place page (no API key)
# ---------------------------------------------------------------------------

class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = a.get("property") or a.get("name") or a.get("itemprop")
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"]
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse_place_page(page_html: str) -> dict:
    """Read name, address and photo from the Open Graph tags of a place page.

    Google renders og:title as "Name · Street 1, 00100 City" and og:image as a
    googleusercontent photo (or a static map when the place has no photo).
    """
    mp = _MetaParser()
    mp.feed(page_html)
    out: dict = {}
    title = mp.meta.get("og:title") or mp.meta.get("name") or ""
    if "·" in title:
        name, _, address = title.partition("·")
        out["name"] = name.strip()
        address = address.strip()
        if address and not address.lower().startswith("google maps"):
            out["address"] = address
    elif title and title.strip().lower() != "google maps":
        out["name"] = title.strip()

    image = mp.meta.get("og:image") or mp.meta.get("image")
    if image and "staticmap" not in image and "maps/api" not in image:
        out["image_url"] = upsize_google_photo(html.unescape(image))
    return out


def upsize_google_photo(url: str, w: int = 800, h: int = 600) -> str:
    """googleusercontent URLs carry size in a suffix like '=w86-h86-k-no'.

    The 'p' flag asks Google to crop to exactly w x h instead of fitting inside it.
    """
    if "googleusercontent.com" not in url:
        return url
    return re.sub(r"=[swh]\d+[^/?]*$", f"=w{w}-h{h}-p-k-no", url)


def _dig(data, *path):
    """Safe nested lookup in Google's positional JSON arrays."""
    for i in path:
        if not isinstance(data, list) or i >= len(data) or data[i] is None:
            return None
        data = data[i]
    return data


def parse_preview(text: str) -> dict:
    """Parse the JSON behind Google Maps' place panel (/maps/preview/place).

    It is an undocumented, positional format, so every field is optional and a
    layout change only loses that field instead of breaking the build.
    """
    import json

    body = text[text.find("\n") + 1:] if text.startswith(")]}'") else text
    try:
        p = _dig(json.loads(body), 6)
    except ValueError:
        return {}
    if not isinstance(p, list):
        return {}

    out: dict = {}
    name = _dig(p, 11)
    if isinstance(name, str):
        out["name"] = name
    address = _dig(p, 39)
    if not isinstance(address, str):
        parts = _dig(p, 2)
        address = ", ".join(x for x in parts if isinstance(x, str)) if isinstance(parts, list) else None
    if address:
        out["address"] = re.sub(r",\s*(Finland|Suomi)$", "", address)
    lat, lng = _dig(p, 9, 2), _dig(p, 9, 3)
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        out["lat"], out["lng"] = round(lat, 7), round(lng, 7)
    cats = _dig(p, 13)
    if isinstance(cats, list):
        out["categories"] = [c for c in cats if isinstance(c, str)]
    rating, reviews = _dig(p, 4, 7), _dig(p, 4, 8)
    if isinstance(rating, (int, float)):
        out["rating"] = rating
        if isinstance(reviews, int):
            out["reviews"] = reviews
    website = _dig(p, 7, 0)
    if isinstance(website, str) and website.startswith("http"):
        out["website"] = website
    phone = _dig(p, 178, 0, 0)
    if isinstance(phone, str):
        out["phone"] = phone
    for key in (72, 51, 37):  # main photo, photo strip, street view
        photo = _dig(p, key, 0, 0, 6, 0)
        if isinstance(photo, str) and "googleusercontent.com" in photo:
            out["image_url"] = upsize_google_photo(photo)
            break
    return out


_RE_PREVIEW = re.compile(r'<link href="(/maps/preview/place\?[^"]+)"')


def fetch_place_page(session: requests.Session, place: Place) -> dict:
    # Use the link exactly as the short link resolved: its data= segment carries
    # the place id. A hand-built URL loses it and Google falls back to a text search.
    url = place.resolved_url
    if "hl=" not in url:
        url += ("&" if "?" in url else "?") + "hl=en"
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    if "consent.google" in r.url:
        raise RuntimeError("Google returned a cookie-consent page")

    out = parse_place_page(r.text)
    # Google now renders the place panel with JavaScript, and the page's own
    # meta tags only describe "Google Maps". The panel's data is linked from the
    # page head, so fetch that too.
    m = _RE_PREVIEW.search(r.text)
    if m:
        pr = session.get("https://www.google.com" + html.unescape(m.group(1)), timeout=TIMEOUT)
        if pr.ok:
            out = {**out, **parse_preview(pr.text)}
    return out


# ---------------------------------------------------------------------------
# OpenStreetMap Nominatim
# ---------------------------------------------------------------------------

_last_nominatim = 0.0


def fetch_nominatim(session: requests.Session, lat: float, lng: float) -> str | None:
    global _last_nominatim
    wait = 1.1 - (time.monotonic() - _last_nominatim)
    if wait > 0:
        time.sleep(wait)
    _last_nominatim = time.monotonic()
    r = session.get(
        "https://nominatim.openstreetmap.org/reverse",
        params={"lat": lat, "lon": lng, "format": "jsonv2", "addressdetails": 1, "zoom": 18},
        headers={"User-Agent": NOMINATIM_UA},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return format_osm_address(r.json().get("address") or {})


def format_osm_address(a: dict) -> str | None:
    street = " ".join(x for x in (a.get("road") or a.get("pedestrian"), a.get("house_number")) if x)
    city = a.get("city") or a.get("town") or a.get("municipality") or a.get("village")
    tail = " ".join(x for x in (a.get("postcode"), city) if x)
    parts = [x for x in (street, tail) if x]
    return ", ".join(parts) or None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RE_CITY = re.compile(r"\b\d{5}\s+([A-Za-zÅÄÖåäöÉé\- ]+?)\s*(?:,|$)")


def city_from_address(address: str | None) -> str | None:
    """Finnish addresses end in '00580 Helsinki'; take the word after the postcode."""
    if not address:
        return None
    m = _RE_CITY.search(address)
    if not m:
        return None
    city = m.group(1).strip()
    return city.title() if city.isupper() else city


def lookup(session: requests.Session, name: str, url: str) -> Place:
    """Run the whole chain for one restaurant. Never raises for network errors."""
    try:
        resolved = resolve_url(session, url)
    except requests.RequestException as e:
        log.warning("%s: could not resolve link (%s)", name, e)
        return Place(resolved_url=url)

    place = parse_maps_url(resolved)
    place.sources.append("url")

    def merge(data: dict, source: str) -> None:
        used = False
        for k, v in data.items():
            if v and getattr(place, k, None) in (None, ""):
                setattr(place, k, v)
                used = True
        if used:
            place.sources.append(source)

    if not place.address or not place.image_url:
        try:
            merge(fetch_place_page(session, place), "maps-page")
        except (requests.RequestException, RuntimeError) as e:
            log.warning("%s: Maps page lookup failed (%s)", name, e)

    if not place.address and place.lat is not None:
        try:
            addr = fetch_nominatim(session, place.lat, place.lng)
            merge({"address": addr}, "nominatim")
        except requests.RequestException as e:
            log.warning("%s: Nominatim failed (%s)", name, e)

    return place


def download_image(session: requests.Session, url: str, dest: Path, width: int = 640) -> bool:
    """Download, crop to 4:3 and save as WebP. Returns True on success."""
    from PIL import Image, ImageOps

    try:
        r = session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img = ImageOps.fit(img, (width, width * 3 // 4), Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "WEBP", quality=80, method=6)
        return True
    except Exception as e:  # noqa: BLE001 -- any bad image should just be skipped
        log.warning("image download failed for %s (%s)", url, e)
        return False
