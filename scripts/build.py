#!/usr/bin/env python3
"""Build the EatHalal site from restaurants.csv.

    python scripts/build.py              # fetch new/stale details, render _site/
    python scripts/build.py --offline    # no network: cache + CSV only
    python scripts/build.py --refresh    # ignore the cache and look everything up again
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import places  # noqa: E402
import render  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE_MAX_AGE = 30 * 24 * 3600  # refresh lookups monthly
CACHE_VERSION = 2  # bump when the cached fields change

log = logging.getLogger("build")


class CsvError(Exception):
    pass


def norm_header(h: str) -> str:
    return re.sub(r"[^a-z]", "", (h or "").lower())


HEADER_ALIASES = {
    "name": "name",
    "googlemapurl": "url",
    "googlemapsurl": "url",
    "url": "url",
    "mapurl": "url",
    "address": "address",
    "city": "city",
    "imageurl": "image",
    "image": "image",
    "tags": "tags",
}


def read_csv(path: Path) -> list[dict]:
    """Read restaurants.csv; tolerant of spaces in headers and blank lines."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, skipinitialspace=True)
        try:
            header = next(reader)
        except StopIteration:
            raise CsvError(f"{path} is empty")
        cols = [HEADER_ALIASES.get(norm_header(h)) for h in header]
        if "name" not in cols or "url" not in cols:
            raise CsvError(f"{path}: header must contain Name and GoogleMapUrl, got {header}")

        rows, seen = [], set()
        for lineno, raw in enumerate(reader, start=2):
            if not any(c.strip() for c in raw):
                continue
            row = {k: v.strip() for k, v in zip(cols, raw) if k}
            if not row.get("name") or not row.get("url"):
                raise CsvError(f"{path}:{lineno}: Name and GoogleMapUrl are required")
            if not row["url"].startswith(("https://", "http://")):
                raise CsvError(f"{path}:{lineno}: '{row['url']}' is not a link")
            if row["url"] in seen:
                log.warning("%s:%d: duplicate link for %s, skipping", path, lineno, row["name"])
                continue
            seen.add(row["url"])
            rows.append(row)
    return rows


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "restaurant"


def load_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        if data.get("version") == CACHE_VERSION:
            return data.get("places", {})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {}


def save_cache(path: Path, entries: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": CACHE_VERSION, "places": entries}, indent=1, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path, default=ROOT / "restaurants.csv")
    ap.add_argument("--out", type=Path, default=ROOT / "_site")
    ap.add_argument("--cache", type=Path, default=ROOT / ".cache")
    ap.add_argument("--offline", action="store_true", help="never touch the network")
    ap.add_argument("--refresh", action="store_true", help="ignore cached lookups")
    ap.add_argument("--base-url", default=os.environ.get("SITE_URL", ""), help="public URL, for meta tags")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        rows = read_csv(args.csv)
    except CsvError as e:
        log.error("%s", e)
        return 1
    log.info("Read %d restaurants from %s", len(rows), args.csv.name)

    cache_file = args.cache / "places.json"
    img_cache = args.cache / "images"
    cache = {} if args.refresh else load_cache(cache_file)
    session = places.new_session()
    now = time.time()

    restaurants, used_slugs, new_cache = [], set(), {}
    for row in rows:
        url = row["url"]
        entry = cache.get(url)
        stale = not entry or now - entry.get("fetched_at", 0) > CACHE_MAX_AGE
        if stale and not args.offline:
            log.info("Looking up %s", row["name"])
            p = places.lookup(session, row["name"], url)
            entry = {**p.to_dict(), "fetched_at": now}
            # Download the photo now so the cache keeps a copy even if the URL expires.
            if p.image_url:
                img_name = hashlib.sha1(p.image_url.encode()).hexdigest()[:16] + ".webp"
                if (img_cache / img_name).exists() or places.download_image(session, p.image_url, img_cache / img_name):
                    entry["image_file"] = img_name
        elif stale and args.offline and not entry:
            entry = places.parse_maps_url(url).to_dict()  # works for long URLs only
        new_cache[url] = entry

        # CSV values beat anything found online.
        override_img = row.get("image")
        image_file = entry.get("image_file")
        if override_img and not args.offline:
            img_name = hashlib.sha1(override_img.encode()).hexdigest()[:16] + ".webp"
            if (img_cache / img_name).exists() or places.download_image(session, override_img, img_cache / img_name):
                image_file = img_name
                new_cache[url] = {**entry, "override_image_file": img_name}
        elif override_img:
            image_file = entry.get("override_image_file", image_file)

        address = row.get("address") or entry.get("address")
        slug = slugify(row["name"])
        while slug in used_slugs:
            slug += "-2"
        used_slugs.add(slug)

        r = {
            "id": slug,
            "name": row["name"],
            "address": address,
            "city": row.get("city") or places.city_from_address(address),
            "lat": entry.get("lat"),
            "lng": entry.get("lng"),
            "url": url,
            "image": f"images/{image_file}" if image_file and (img_cache / image_file).exists() else None,
            "tags": [t.strip() for t in (row.get("tags") or "").split(";") if t.strip()],
            "category": (entry.get("categories") or [None])[0],
            "rating": entry.get("rating"),
            "reviews": entry.get("reviews"),
            "website": entry.get("website"),
            "phone": entry.get("phone"),
        }
        if not r["address"]:
            log.warning("%s: no address found — add an Address column to fix", row["name"])
        if r["lat"] is None:
            log.warning("%s: no coordinates found, it will not appear on the map", row["name"])
        restaurants.append(r)

    if not args.offline:
        save_cache(cache_file, new_cache)

    render.render_site(restaurants, out=args.out, img_cache=img_cache, base_url=args.base_url)
    log.info("Wrote %d restaurants to %s", len(restaurants), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
