"""Render the static site into an output directory."""
from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
SITE_SRC = ROOT / "site"


def directions_url(r: dict) -> str:
    if r.get("lat") is not None:
        dest = f"{r['lat']},{r['lng']}"
    else:
        dest = ", ".join(x for x in (r["name"], r.get("address")) if x)
    return "https://www.google.com/maps/dir/?api=1&destination=" + quote(dest)


def search_text(r: dict) -> str:
    parts = (r["name"], r.get("address"), r.get("city"), r.get("category"), *r["tags"])
    return " ".join(x for x in parts if x)


def short_category(cat: str | None) -> str | None:
    """'Pakistani restaurant' -> 'Pakistani'; generic 'Restaurant' stays as is."""
    if not cat:
        return None
    short = re.sub(r"\s+restaurant$", "", cat, flags=re.I).strip()
    return short or cat


def fmt_reviews(n: int | None) -> str:
    if not n:
        return ""
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def render_card(r: dict) -> str:
    e = lambda s: escape(s or "", quote=True)  # noqa: E731
    if r.get("image"):
        photo = f'<img src="{e(r["image"])}" alt="" loading="lazy" decoding="async" width="640" height="480">'
    else:
        photo = f'<span class="card-initial" aria-hidden="true">{e(r["name"][:1].upper())}</span>'
    tags = "".join(f"<li>{e(t)}</li>" for t in r["tags"])
    tags_html = f'<ul class="card-tags" aria-label="Tags">{tags}</ul>' if tags else ""
    address = (
        f'<p class="card-address">{e(r["address"])}</p>'
        if r.get("address")
        else '<p class="card-address card-address--missing">Address on Google Maps</p>'
    )
    meta = []
    if r.get("category"):
        meta.append(f'<span class="card-cat">{e(short_category(r["category"]))}</span>')
    if r.get("rating"):
        n = r.get("reviews")
        label = f'Rated {r["rating"]:.1f} out of 5 on Google' + (f" from {n:,} reviews" if n else "")
        count = f'<span class="card-reviews">({fmt_reviews(n)})</span>' if n else ""
        meta.append(
            f'<span class="card-rating" aria-label="{label}"><svg viewBox="0 0 20 20" aria-hidden="true">'
            f'<path d="M10 1.5l2.6 5.6 6.1.7-4.5 4.2 1.2 6L10 15l-5.4 3 1.2-6L1.3 7.8l6.1-.7z"/></svg>'
            f'{r["rating"]:.1f}{count}</span>'
        )
    meta_html = f'<p class="card-meta">{"".join(meta)}</p>' if meta else ""
    links = []
    if r.get("phone"):
        tel = re.sub(r"[^+\d]", "", r["phone"])
        links.append(f'<a class="card-link" href="tel:{e(tel)}">Call<span class="sr-only"> {e(r["name"])}</span></a>')
    if r.get("website"):
        links.append(f'<a class="card-link" href="{e(r["website"])}" target="_blank" rel="noopener">Website<span class="sr-only"> of {e(r["name"])}</span></a>')
    links_html = "".join(links)
    lat = "" if r.get("lat") is None else f' data-lat="{r["lat"]}" data-lng="{r["lng"]}"'
    return f"""<li class="card" id="r-{e(r['id'])}" data-id="{e(r['id'])}" data-city="{e(r.get('city'))}" data-search="{e(search_text(r))}"{lat}>
  <a class="card-photo{' card-photo--empty' if not r.get('image') else ''}" href="{e(r['url'])}" target="_blank" rel="noopener" tabindex="-1" aria-hidden="true">{photo}</a>
  <div class="card-body">
    <h3 class="card-name"><a href="{e(r['url'])}" target="_blank" rel="noopener">{e(r['name'])}</a></h3>
    {meta_html}
    {address}
    {tags_html}
    <div class="card-foot">
      <span class="card-distance" hidden></span>
      {links_html}
      <a class="card-directions" href="{e(directions_url(r))}" target="_blank" rel="noopener">Directions<span class="sr-only"> to {e(r['name'])}</span></a>
    </div>
  </div>
</li>"""


def render_city_chips(restaurants: list[dict]) -> str:
    counts = Counter(r["city"] for r in restaurants if r.get("city"))
    chips = [f'<button type="button" class="chip" data-city="" aria-pressed="true">All <span>{len(restaurants)}</span></button>']
    for city, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        c = escape(city, quote=True)
        chips.append(f'<button type="button" class="chip" data-city="{c}" aria-pressed="false">{c} <span>{n}</span></button>')
    return "\n".join(chips)


def render_site(restaurants: list[dict], out: Path, img_cache: Path, base_url: str = "") -> None:
    restaurants = sorted(restaurants, key=lambda r: r["name"].casefold())
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE_SRC / "assets", out / "assets")

    (out / "images").mkdir(parents=True)
    for r in restaurants:
        if r.get("image"):
            shutil.copy2(img_cache / Path(r["image"]).name, out / r["image"])

    cities = {r["city"] for r in restaurants if r.get("city")}
    now = datetime.now(timezone.utc)
    data_json = json.dumps(
        [{k: r.get(k) for k in ("id", "name", "address", "city", "lat", "lng", "url", "image", "category", "rating")} for r in restaurants],
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")

    city_phrase = f"{len(cities)} {'city' if len(cities) == 1 else 'cities'}" if cities else "Finland"
    replacements = {
        "{{CARDS}}": "\n".join(render_card(r) for r in restaurants),
        "{{CITY_CHIPS}}": render_city_chips(restaurants),
        "{{DATA_JSON}}": data_json,
        "{{COUNT}}": str(len(restaurants)),
        "{{RESTAURANT_WORD}}": "restaurant" if len(restaurants) == 1 else "restaurants",
        "{{CITY_PHRASE}}": city_phrase,
        "{{UPDATED_ISO}}": now.isoformat(timespec="minutes"),
        "{{UPDATED}}": now.strftime("%-d %B %Y"),
        "{{YEAR}}": str(now.year),
        "{{BASE_URL}}": escape(base_url.rstrip("/"), quote=True),
    }
    page = (SITE_SRC / "index.html").read_text(encoding="utf-8")
    for k, v in replacements.items():
        page = page.replace(k, v)
    (out / "index.html").write_text(page, encoding="utf-8")

    (out / "restaurants.json").write_text(
        json.dumps({"updated": now.isoformat(timespec="seconds"), "restaurants": restaurants}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (out / ".nojekyll").write_text("")
