import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build  # noqa: E402
import places  # noqa: E402

TANDOORI = (
    "https://www.google.com/maps/place/Tandoori+Villa+Kalasatama/@60.2594843,24.7540322,11z/"
    "data=!4m6!3m5!1s0x4692093de1d04651:0x43fc2f18fe5e164a!8m2!3d60.1853484!4d24.983638!16s%2Fg%2F11jtdp_p0n"
    "?entry=tts&g_ep=EgoyMDI2MTAyMC4wIPu8ASoASAFQAw%3D%3D"
)


def test_parse_place_url_prefers_pin_over_viewport():
    p = places.parse_maps_url(TANDOORI)
    assert p.name == "Tandoori Villa Kalasatama"
    assert (p.lat, p.lng) == (60.1853484, 24.983638)
    assert p.feature_id == "0x4692093de1d04651:0x43fc2f18fe5e164a"


def test_parse_viewport_only_url():
    p = places.parse_maps_url("https://www.google.com/maps/place/Deli+Lunch/@60.17,24.94,17z")
    assert p.name == "Deli Lunch"
    assert (p.lat, p.lng) == (60.17, 24.94)


def test_parse_query_coordinates():
    p = places.parse_maps_url("https://maps.google.com/?q=60.2,24.9")
    assert (p.lat, p.lng) == (60.2, 24.9)


def test_parse_place_page_og_tags():
    page = """<html><head><title>Google Maps</title>
    <meta content="Tandoori Villa Kalasatama · Hermannin rantatie 12, 00580 Helsinki" property="og:title">
    <meta content="★★★★★ · Indian restaurant" property="og:description">
    <meta content="https://lh5.googleusercontent.com/p/AF1QipABC=w86-h86-k-no" property="og:image">
    </head></html>"""
    d = places.parse_place_page(page)
    assert d["name"] == "Tandoori Villa Kalasatama"
    assert d["address"] == "Hermannin rantatie 12, 00580 Helsinki"
    assert d["image_url"] == "https://lh5.googleusercontent.com/p/AF1QipABC=w800-h600-p-k-no"


def test_parse_place_page_ignores_static_map_image():
    page = '<meta property="og:image" content="https://maps.google.com/maps/api/staticmap?center=1,2">'
    assert "image_url" not in places.parse_place_page(page)


@pytest.mark.parametrize(
    "address,city",
    [
        ("Hermannin rantatie 12, 00580 Helsinki", "Helsinki"),
        ("Tapiolantie 3, 02100 Espoo, Finland", "Espoo"),
        ("Hämeenkatu 1, 33100 TAMPERE", "Tampere"),
        ("Some street without postcode", None),
        (None, None),
    ],
)
def test_city_from_address(address, city):
    assert places.city_from_address(address) == city


def test_osm_address_format():
    a = {"road": "Mannerheimintie", "house_number": "5", "postcode": "00100", "city": "Helsinki"}
    assert places.format_osm_address(a) == "Mannerheimintie 5, 00100 Helsinki"


def test_read_csv_tolerates_spaced_header_and_blank_lines(tmp_path):
    f = tmp_path / "r.csv"
    f.write_text(
        "Name, GoogleMapUrl, Tags\n"
        "A,https://maps.app.goo.gl/x, Buffet;Pizza\n\n"
        "B,https://maps.app.goo.gl/y\n"
        "Dup,https://maps.app.goo.gl/x\n"
    )
    rows = build.read_csv(f)
    assert [r["name"] for r in rows] == ["A", "B"]
    assert rows[0]["tags"] == "Buffet;Pizza"


def test_read_csv_rejects_missing_url(tmp_path):
    f = tmp_path / "r.csv"
    f.write_text("Name,GoogleMapUrl\nA,\n")
    with pytest.raises(build.CsvError):
        build.read_csv(f)


def test_slugify():
    assert build.slugify("Restaurant Taj Deen Bakery") == "restaurant-taj-deen-bakery"
    assert build.slugify("Kebab Äijä") == "kebab-aija"


class _Resp:
    def __init__(self, url, text="", status=200):
        self.url, self.text, self.status_code, self.ok = url, text, status, status < 400

    def raise_for_status(self):
        if not self.ok:
            raise places.requests.HTTPError(self.status_code)


class _FakeSession:
    """Short link -> TANDOORI, place page -> OG tags, Nominatim never needed."""

    def get(self, url, **kw):
        if "goo.gl" in url:
            return _Resp(TANDOORI)
        if "/maps/preview/place" in url:
            return _Resp(url, _preview_payload())
        if "/maps/place/" in url:
            return _Resp(url, '<meta property="og:title" content="Tandoori Villa · Hermannin rantatie 12, 00580 Helsinki">'
                              '<meta property="og:image" content="https://lh5.googleusercontent.com/p/X=s86">'
                              '<link href="/maps/preview/place?pb=x">')
        raise AssertionError(f"unexpected request {url}")


def test_lookup_chain():
    p = places.lookup(_FakeSession(), "Tandoori", "https://maps.app.goo.gl/abc")
    assert p.lat == 60.1853484
    # The preview data (Google's own panel) wins over the page's meta tags.
    assert p.address == "Sörnäistenlaituri 3, 00540 Helsinki"
    assert p.rating == 4.7
    assert p.image_url.endswith("=w800-h600-p-k-no")
    assert p.sources == ["url", "maps-page"]


def _preview_payload():
    import json
    place = [None] * 180
    place[2] = ["Sörnäistenlaituri 3", "00540 Helsinki", "Finland"]
    place[4] = [None] * 7 + [4.7, 1356]
    place[7] = ["https://tandoorivilla.fi/", "tandoorivilla.fi"]
    place[9] = [None, None, 60.1853484, 24.983638]
    place[11] = "Tandoori Villa Kalasatama"
    place[13] = ["Indian restaurant", "Pakistani restaurant"]
    place[39] = "Sörnäistenlaituri 3, 00540 Helsinki, Finland"
    place[72] = [[[None] * 6 + [["https://lh3.googleusercontent.com/grass-cs/ABC=w86-h114-k-no"]]]]
    place[178] = [["+358 50 5478888"]]
    return ")]}'\n" + json.dumps([None] * 6 + [place])


def test_parse_preview():
    d = places.parse_preview(_preview_payload())
    assert d["address"] == "Sörnäistenlaituri 3, 00540 Helsinki"
    assert d["categories"][0] == "Indian restaurant"
    assert (d["rating"], d["reviews"]) == (4.7, 1356)
    assert d["website"] == "https://tandoorivilla.fi/"
    assert d["phone"] == "+358 50 5478888"
    assert d["image_url"].endswith("=w800-h600-p-k-no")


def test_parse_preview_survives_garbage():
    assert places.parse_preview(")]}'\nnot json") == {}
    assert places.parse_preview(")]}'\n[1,2,3]") == {}
